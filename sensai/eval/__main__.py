"""python -m sensai.eval [--limit n] [--model m] [--judge-model m] [--no-judge] [--only id,id] [--record]
python -m sensai.eval --attacks [--repeat n] [--no-guard] [--only id,id] [--model m], ev4 in attacks.py
python -m sensai.eval --rag, r1 in rag.py, the search on labelled questions, no cloud call

each question gets a fresh session w/ the quant-data and sandbox servers (web and fetch cant be
frozen), a fixed profile (benchmark SPY) and the snapshot's date
--record runs live and builds the snapshot in eval/data/, the other runs are offline on it -> same
data for every model
"""

import argparse
import json
import os
import sys
from datetime import datetime

import yaml

from sensai.chat import Session
from sensai.config import ConfigError, load_config
from sensai import sandbox
from sensai.data import REPO
from sensai.data import rag as rag_data
from sensai.eval import attacks, rag, report
from sensai.eval.runner import run_question
from sensai.home import user_dir
from sensai.mcp_client import ToolHub
from sensai.ollama import OllamaClient, OllamaError, QuotaHit

EVAL = REPO / "eval"
SERVERS = ("quant-data", "sandbox")
# web and fetch started for their real schemas and limits, AttackHub doesnt call them
ATTACK_SERVERS = (*SERVERS, "web", "fetch", "rag")
PROFILE = {"benchmark": "SPY"}


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m sensai.eval", description="sensai eval on frozen data")
    p.add_argument("--limit", type=int, help="run the 1st n questions only, saves the cloud quota")
    p.add_argument("--only", help="question ids, comma separated")
    p.add_argument("--model", help="model to evaluate, overrides config.yaml")
    p.add_argument("--judge-model", help="judge model, overrides judge_model in config.yaml")
    p.add_argument("--no-judge", action="store_true", help="skip the judge (1 model call less per question)")
    p.add_argument("--record", action="store_true", help="run live and save the data in eval/data/ (the snapshot)")
    p.add_argument("--attacks", action="store_true", help="the attacks of eval/attacks.yaml + the malformed inputs")
    p.add_argument("--repeat", type=int, default=1, help="--attacks: runs of each model attack, the models are random")
    p.add_argument("--no-guard", action="store_true", help="--attacks: w/o the rule on instructions in tool results")
    p.add_argument("--rag", action="store_true", help="the news search on eval/rag.yaml, no cloud call")
    p.add_argument("--questions", default=str(EVAL / "questions.yaml"))
    p.add_argument("--config", default=str(REPO / "config.yaml"))
    return p.parse_args(argv)


def setup_env(record):
    """the vars the data layer reads, set before the servers start -> they inherit them"""
    data = EVAL / "data"
    snap = data / "snapshot.json"
    if record:
        today = datetime.now().date().isoformat()
        os.environ.pop("SENSAI_OFFLINE", None)
    elif snap.is_file():
        today = json.loads(snap.read_text(encoding="utf-8"))["today"]
        os.environ["SENSAI_OFFLINE"] = "1"
    else:
        raise SystemExit("sensai.eval: no snapshot in eval/data/, record 1 first: python -m sensai.eval --record")
    os.environ.update({"SENSAI_DATA": str(data), "SENSAI_TODAY": today, "SENSAI_OUT": str(EVAL / "out")})
    return today, snap


def run_attacks(args, cfg, client, today):
    """the malformed inputs 1st, they are free, then each attack on a fresh session"""
    picked = yaml.safe_load(open(EVAL / "attacks.yaml", encoding="utf-8"))["attacks"]
    keep = set(args.only.split(",")) if args.only else None
    picked = [a for a in picked if not keep or a["id"] in keep]
    picked = picked[:args.limit] if args.limit else picked
    results = [r for r in attacks.inputs() if not keep or r["id"] in keep]
    decoy = attacks.write_decoy(EVAL / "out" / "attacks")
    hub = ToolHub(log_dir=user_dir() / "logs")
    for w in hub.start([s for s in cfg.get("mcp_servers") or [] if s["name"] in ATTACK_SERVERS]):
        print(f"[warning] {w}")

    def make_session(attack_hub):
        return Session(client, cfg["model"], cfg.get("system_prompt"), show_thinking=False, profile=attacks.PROFILE,
                       hub=attack_hub, notes=False, guard=not args.no_guard, max_steps=cfg.get("max_steps", 12),
                       token_budget=cfg.get("token_budget", 60000))

    try:
        for n in range(args.repeat):
            for i, a in enumerate(picked, 1):
                print(f"[run {n + 1}/{args.repeat}, {i}/{len(picked)}] {a['id']}", end=" ", flush=True)
                r = attacks.run_attack(a, make_session, hub, decoy)
                results.append(r)
                print(f"{r['secs']}s, {r['outcome']}")
    except QuotaHit as e:
        print(f"\nstopped: {e}")
    except KeyboardInterrupt:
        print("\nstopped, the results so far are kept")
    finally:
        hub.close()
    meta = {"model": cfg["model"], "today": today, "guard": not args.no_guard, "repeat": args.repeat,
            "sandbox": sandbox.pick_backend(), "attacks": True}
    s = attacks.summary(results)
    print("\n" + attacks.table(results, s, meta))
    print(f"\nsaved: {report.save(results, s, meta, EVAL / 'results')}")
    return 0


def run_rag(args, today):
    """in this process, the search needs the local ollama and the snapshot"""
    why = rag_data.unavailable()
    if why:
        print(f"sensai.eval: {why}", file=sys.stderr)
        return 1
    cases = yaml.safe_load(open(EVAL / "rag.yaml", encoding="utf-8"))["questions"]
    keep = set(args.only.split(",")) if args.only else None
    results = [rag.run_case(c) for c in cases if not keep or c["id"] in keep]
    meta = {"model": rag_data.model(), "today": today, "rag": True}
    s = rag.summary(results)
    print(rag.table(results, s, meta))
    print(f"\nsaved: {report.save(results, s, meta, EVAL / 'results')}")
    return 0


def main(argv=None):
    args = parse_args(argv)
    if args.attacks and args.record:
        raise SystemExit("sensai.eval: --attacks runs on the snapshot, record it apart")
    today, snap = setup_env(args.record)
    if args.rag:
        return run_rag(args, today)
    try:
        cfg = load_config(args.config, model=args.model)
        client = OllamaClient(cfg["ollama"]["host"], cfg["ollama"].get("timeout", 120))
        client.check_auth()
        client.check_model(cfg["model"])
        judge_model = None if args.no_judge or args.record or args.attacks else (args.judge_model or cfg.get("judge_model") or cfg["model"])
        if judge_model:
            client.check_model(judge_model)
    except (ConfigError, OllamaError) as e:
        print(f"sensai.eval: {e}", file=sys.stderr)
        return 1

    if args.attacks:
        return run_attacks(args, cfg, client, today)
    questions = yaml.safe_load(open(args.questions, encoding="utf-8"))["questions"]
    if args.only:
        keep = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in keep]
    questions = questions[:args.limit] if args.limit else questions

    hub = ToolHub(log_dir=user_dir() / "logs")
    for w in hub.start([s for s in cfg.get("mcp_servers") or [] if s["name"] in SERVERS]):
        print(f"[warning] {w}")

    def make_session():
        # no note tool -> same tools and system msg as the oct 28 run
        return Session(client, cfg["model"], cfg.get("system_prompt"), show_thinking=False, profile=PROFILE,
                       hub=hub, notes=False, guard=False, max_steps=cfg.get("max_steps", 12), token_budget=cfg.get("token_budget", 60000))

    meta = {"model": cfg["model"], "judge_model": judge_model, "today": today, "record": args.record,
            "questions_file": args.questions}
    results = []
    try:
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}", end=" ", flush=True)
            r = run_question(q, make_session, client, judge_model)
            results.append(r)
            print("error" if "error" in r else f"{r['secs']}s, {r['checks']['unsourced']} flagged")
    except QuotaHit as e:
        print(f"\nstopped: {e}")
    except KeyboardInterrupt:
        print("\nstopped, the results so far are kept")
    finally:
        hub.close()
    if args.record:
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(json.dumps({"today": today, "recorded": datetime.now().isoformat(timespec="seconds"),
                                    "model": cfg["model"]}, indent=1), encoding="utf-8")
    s = report.summary(results)
    print("\n" + report.table(results, s, meta))
    print(f"\nsaved: {report.save(results, s, meta, EVAL / 'results')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
