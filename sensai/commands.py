"""/cmds of the repl, 1 func each + the CMDS table"""

import sys

from sensai import profile as prof
from sensai.ollama import OllamaError
from sensai.sessions import SessionError
from sensai.ui import DIM, RESET

HELP = """cmds:
  /model            show the current model and the available ones
  /model <name>     switch model, history is kept
  /think            show or hide the model's thinking
  /tools            the MCP servers and the tools the model can call
  /clear            start a new session, the current one stays saved
  /sessions         the 10 most recent sessions
  /resume <id>      reopen a session (a prefix of the id or "last" works)
  /profile          show your profile
  /profile setup    answer the profile questions again
  /profile edit     open the profile in your editor
  /remember <fact>  add a note sensai always keeps in mind
  /forget <n>       remove note n (numbers from /profile)
  /help             this list
  /exit             quit (Ctrl+D works too)
Ctrl+C during an answer stops it"""


def handle_cmd(session, text):
    """returns True when the repl should stop"""
    cmd, _, arg = text.partition(" ")
    arg = arg.strip()
    if cmd == "/exit":
        return True
    handler = CMDS.get(cmd)
    if handler is None:
        print(f"unknown cmd {cmd}, /help for the list")
        return False
    try:
        handler(session, arg)
    except (OllamaError, SessionError, prof.ProfileError) as e:
        print(f"[error] {e}")
    return False


def count_turns(messages):
    """1 turn = 1 question, tool msgs in between dont count"""
    return sum(1 for m in messages if m.get("role") == "user")


def last_exchange(messages):
    """last question + the answer to it, skipping tool msgs and tool call rounds w/o text"""
    users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not users:
        return []
    rest = messages[users[-1]:]
    answers = [m for m in rest if m.get("role") == "assistant" and m.get("content")]
    return [rest[0], *answers[-1:]]


def resumed_msg(session, record, tty=True):
    """what gets printed on resume: id, title, nb of turns, the last exchange dim"""
    turns = session.turns()
    lines = [f"resumed {session.id}: {session.title or '(untitled)'} ({count_turns(turns)} turns)"]
    if record.get("model") and record["model"] != session.model:
        lines.append(f"was on {record['model']}, now {session.model}")
    dim, reset = (DIM, RESET) if tty else ("", "")
    for m in last_exchange(turns):
        text = " ".join(m["content"].split())
        who = "you" if m["role"] == "user" else "sensai"
        lines.append(f"{dim}{who}: {text[:200]}{'...' if len(text) > 200 else ''}{reset}")
    return "\n".join(lines)


def cmd_help(session, arg):
    print(HELP)


def cmd_think(session, arg):
    session.show_thinking = not session.show_thinking
    print(f"thinking {'shown' if session.show_thinking else 'hidden'}")


def cmd_tools(session, arg):
    hub = session.hub
    if not hub or not hub.servers:
        print("no MCP server, add some under mcp_servers in config.yaml")
        return
    for name, srv in hub.servers.items():
        if srv["status"] == "up":
            print(f"{name}: {', '.join(srv['tools']) or '(no tools)'}")
        else:
            print(f"{name}: down, {srv['status']}")


def cmd_model(session, arg):
    if not arg:
        print(f"current: {session.model}")
        print("available: " + ", ".join(session.client.list_models()))
        return
    session.client.check_model(arg)
    session.model = arg
    print(f"switched to {arg}, history kept")


def cmd_clear(session, arg):
    old = session.id if session.turns() else None
    session.clear()
    print(f"new session {session.id}" + (f", {old} stays saved (/resume {old})" if old else ""))


def cmd_sessions(session, arg):
    if not session.store:
        print("sessions arent saved in this run")
        return
    records, bad = session.store.recent(10)
    if not records:
        print("no saved session yet")
    for r in records:
        turns = count_turns(r["messages"])
        mark = "*" if r["id"] == session.id else " "
        print(f"{mark} {r['id']}  {r.get('updated', '')[:16].replace('T', ' ')}  {turns:>3} turns  "
              f"{r.get('model', '?'):<14} {r.get('title') or '(untitled)'}")
    if bad:
        print(f"({bad} corrupt file(s) skipped)")


def cmd_resume(session, arg):
    if not session.store:
        print("sessions arent saved in this run")
        return
    record = session.store.load(arg or "last")
    session.load_record(record)
    print(resumed_msg(session, record, sys.stdout.isatty()))


def cmd_profile(session, arg):
    if arg == "setup":
        try:
            p = prof.setup(current=session.profile)
        except (KeyboardInterrupt, EOFError):
            print("\nsetup cancelled, nothing changed")
            return
        prof.save_profile(session.profile_path, p)
        session.set_profile(p)
        print("profile saved")
    elif arg == "edit":
        try:
            p = prof.edit(session.profile_path, session.profile)
        except prof.ProfileError as e:
            raise prof.ProfileError(f"{e}\nthe old profile is still in use, /profile edit again to fix the file") from None
        session.set_profile(p)
        print("profile reloaded")
    elif not arg:
        print(prof.show(session.profile, session.profile_path))
    else:
        print("usage: /profile, /profile setup or /profile edit")


def cmd_remember(session, arg):
    session.set_profile(prof.remember(session.profile_path, session.profile, arg))
    print(f"noted ({len(session.profile['notes'])} note(s)), /profile to see them")


def cmd_forget(session, arg):
    p, removed = prof.forget(session.profile_path, session.profile, arg)
    session.set_profile(p)
    print(f"forgot: {removed}")


CMDS = {
    "/help": cmd_help,
    "/think": cmd_think,
    "/tools": cmd_tools,
    "/model": cmd_model,
    "/clear": cmd_clear,
    "/sessions": cmd_sessions,
    "/resume": cmd_resume,
    "/profile": cmd_profile,
    "/remember": cmd_remember,
    "/forget": cmd_forget,
}
