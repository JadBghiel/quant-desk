"""runs the python the model writes, in docker or a limited subprocess

each run gets its own folder out/<run_id>/ w/ the code saved as script.py, the run works in it
-> a plot saved w/ a relative name lands there, data/ is mounted at the same absolute path as on
the host -> the `path` the market tools return works the same in both backends
no MCP here, the server in sensai/servers/sandbox.py is a thin layer on top
"""

import os
import secrets
import subprocess
import sys
import time
from datetime import datetime

from sensai.data import data_dir, out_dir

IMAGE = "sensai-sandbox"
TIMEOUT = 30  # secs per run
MEMORY = "512m"
CPUS = "1"
MAX_STDOUT = 4000  # chars
STDERR_LINES = 40  # the end of a traceback is the useful part

_docker_ok = None


def docker_ready():
    """docker cli there, daemon up and the image built, checked once per process"""
    global _docker_ok
    if _docker_ok is None:
        try:
            r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=15)
            _docker_ok = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _docker_ok = False
    return _docker_ok


def pick_backend(backend=None):
    """docker or subprocess, $SENSAI_SANDBOX forces one, auto = docker when its ready"""
    backend = backend or os.environ.get("SENSAI_SANDBOX") or "auto"
    if backend not in ("auto", "docker", "subprocess"):
        raise ValueError(f"SENSAI_SANDBOX must be auto, docker or subprocess, got {backend!r}")
    if backend == "auto":
        return "docker" if docker_ready() else "subprocess"
    return backend


def cache_dir():
    """shared by all runs -> matplotlib builds its font cache (~7s) once for all of them"""
    d = out_dir() / ".cache"
    d.mkdir(exist_ok=True)
    return d


def new_run_dir():
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    d = out_dir() / run_id
    d.mkdir()
    return run_id, d


def docker_cmd(run_id, run_dir, data, cache):
    """no network, cpu + mem + pids caps, read only root fs, data/ read only, the run dir writable
    --mount bc -v splits on : and the repo path has a space"""
    cmd = ["docker", "run", "--rm", "--name", f"sensai-run-{run_id}", "--network", "none",
           "--cpus", CPUS, "--memory", MEMORY, "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp",
           "-e", "MPLBACKEND=Agg", "-e", "HOME=/tmp", "-e", f"MPLCONFIGDIR={cache}",
           "--mount", f"type=bind,src={data},dst={data},readonly",
           "--mount", f"type=bind,src={run_dir},dst={run_dir}",
           "--mount", f"type=bind,src={cache},dst={cache}",
           "-w", str(run_dir)]
    if hasattr(os, "getuid"):
        # the user owns the files written in out/
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    return cmd + [IMAGE, "python", "script.py"]


def _limit_cpu(secs):
    def apply():
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (secs, secs + 1))
    return apply


def subprocess_env(run_dir):
    """PATH + a HOME in the run dir, the api keys of .env stay out of the agent's code"""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(run_dir), "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(cache_dir())}


def _tail(text, lines):
    return "\n".join(text.strip().splitlines()[-lines:])


def run(code, timeout=TIMEOUT, backend=None):
    """-> {ok, backend, run_id, exit_code, timed_out, secs, stdout, stderr, files, dir}"""
    backend = pick_backend(backend)
    run_id, run_dir = new_run_dir()
    (run_dir / "script.py").write_text(code, encoding="utf-8")
    if backend == "docker":
        cmd, kw = docker_cmd(run_id, run_dir, data_dir(), cache_dir()), {}
    else:
        kw = {"env": subprocess_env(run_dir)}
        if os.name == "posix":
            kw["preexec_fn"] = _limit_cpu(timeout)
        # -I: the agent's code cant import from the repo or the user site
        cmd = [sys.executable, "-I", "script.py"]
    t0 = time.monotonic()
    timed_out = False
    try:
        r = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, timeout=timeout, **kw)
        code_, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        timed_out, code_ = True, None
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = f"stopped after {timeout}s"
        if backend == "docker":
            # killing the docker cli leaves the container going
            subprocess.run(["docker", "kill", f"sensai-run-{run_id}"], capture_output=True, timeout=15)
    secs = time.monotonic() - t0
    files = sorted(str(p) for p in run_dir.rglob("*")
                   if p.is_file() and p.name != "script.py" and not p.relative_to(run_dir).parts[0].startswith("."))
    if len(out) > MAX_STDOUT:
        out = out[:MAX_STDOUT] + f"\n[cut, {len(out) - MAX_STDOUT} more chars]"
    return {"ok": code_ == 0, "backend": backend, "run_id": run_id, "exit_code": code_,
            "timed_out": timed_out, "secs": round(secs, 2), "stdout": out, "stderr": _tail(err, STDERR_LINES),
            "files": files, "dir": str(run_dir)}
