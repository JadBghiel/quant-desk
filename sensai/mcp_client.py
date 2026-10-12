"""MCP client: starts the servers from the cfg, lists their tools, runs the calls the model asks for

the mcp sdk is async and the chat is sync, so 1 background thread runs an asyncio loop and keeps
every server's session open for the whole run. the sync methods hand coroutines to that loop
"""

import asyncio
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path

from mcp import Client, StdioServerParameters, stdio_client

START_TIMEOUT = 60  # uvx downloads the server on its 1st run
CALL_TIMEOUT = 90
MAX_RESULT = 8000  # chars, a tool result shouldnt eat the context


def resolve_command(command):
    """`python` -> this interpreter, else the venv's bin/ first so it works w/o activating it"""
    if command in ("python", "python3"):
        return sys.executable
    local = Path(sys.executable).parent / command
    if local.exists():
        return str(local)
    return shutil.which(command) or command


def to_ollama_tool(tool):
    """mcp Tool -> the shape ollama's `tools` param expects"""
    return {"type": "function", "function": {
        "name": tool.name,
        "description": (tool.description or "").strip(),
        "parameters": tool.input_schema or {"type": "object", "properties": {}},
    }}


def result_text(result):
    """CallToolResult -> 1 string for the model, structured content first bc its exact"""
    if result.structured_content is not None:
        data = result.structured_content
        # MCPServer wraps non dict returns in {"result": ...}
        if isinstance(data, dict) and list(data) == ["result"]:
            data = data["result"]
        text = json.dumps(data, ensure_ascii=False, default=str)
    else:
        text = "\n".join(b.text for b in result.content if getattr(b, "type", None) == "text")
        # our server sends indented JSON, compact it to save tokens
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, default=str)
        except ValueError:
            pass
    if len(text) > MAX_RESULT:
        text = text[:MAX_RESULT] + f"\n[cut, {len(text) - MAX_RESULT} more chars]"
    return text


def _quiet_sdk_logs(log_dir):
    """the sdk logs warnings (eg a server line it cant parse) and w/o a handler python prints
    them on stderr, in the middle of the chat. they go to mcp.log instead"""
    logger = logging.getLogger("mcp")
    logger.propagate = False
    if logger.handlers:
        return
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "mcp.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    else:
        handler = logging.NullHandler()
    logger.addHandler(handler)


class ToolHub:
    def __init__(self, log_dir=None):
        self.log_dir = Path(log_dir) if log_dir else None
        _quiet_sdk_logs(self.log_dir)
        self.servers = {}  # name -> {"status": "up" | error msg, "tools": [names]}
        self.tools = []  # ollama schemas
        self._owner = {}  # tool name -> client
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._stop = None
        self._tasks = []
        self._logs = []

    def _run(self, coro, timeout):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # --- startup

    def start(self, servers_cfg):
        """returns the warnings, a server that fails is skipped, the others still work"""
        self._stop = self._run(self._make_event(), 10)
        warnings = []
        for cfg in servers_cfg or []:
            name = cfg.get("name") or cfg.get("command", "?")
            if cfg.get("enabled") is False:
                continue
            ready = self._loop.create_future()
            task = asyncio.run_coroutine_threadsafe(self._serve(name, cfg, ready), self._loop)
            try:
                client, tools, instructions = self._run(self._wait(ready), START_TIMEOUT)
            except Exception as e:
                task.cancel()
                msg = str(e) or type(e).__name__
                self.servers[name] = {"status": msg, "tools": [], "limits": None}
                warnings.append(f"mcp server {name} didnt start: {msg}")
                continue
            self._tasks.append(task)
            names = []
            for tool in tools:
                if tool.name in self._owner:
                    warnings.append(f"tool {tool.name} from {name} skipped, another server already has it")
                    continue
                self._owner[tool.name] = client
                self.tools.append(to_ollama_tool(tool))
                names.append(tool.name)
            # limits from the cfg win: thats how a server we dont control (fetch) gets them
            limits = cfg.get("limits") or instructions
            self.servers[name] = {"status": "up", "tools": names,
                                  "limits": " ".join(limits.split()) if limits else None}
        return warnings

    async def _make_event(self):
        return asyncio.Event()

    @staticmethod
    async def _wait(fut):
        return await fut

    async def _serve(self, name, cfg, ready):
        """1 task per server holds its session open until close(), the sdk's anyio scopes have to
        be entered and exited in the same task"""
        env = {**os.environ, **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
        params = StdioServerParameters(command=resolve_command(cfg["command"]),
                                       args=[str(a) for a in cfg.get("args", [])], env=env, cwd=cfg.get("cwd"))
        try:
            # legacy = the classic initialize handshake, every server version speaks it. fetch is
            # still on mcp 1.x and rejects the discover request "auto" tries 1st
            async with Client(stdio_client(params, errlog=self._errlog(name)), cache=None,
                              mode="legacy") as client:
                listed = await client.list_tools()
                ready.set_result((client, listed.tools, client.instructions))
                await self._stop.wait()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError("cancelled"))
            if not isinstance(e, Exception):
                raise

    def _errlog(self, name):
        # server stderr goes to a file, it would land in the middle of the chat otherwise
        if not self.log_dir:
            f = open(os.devnull, "w")
        else:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            f = open(self.log_dir / f"{name}.log", "a", encoding="utf-8")
        self._logs.append(f)
        return f

    # --- calls

    def call(self, name, args):
        """-> (ok, text). every failure is a msg for the model, nothing raises except Ctrl+C"""
        client = self._owner.get(name)
        if client is None:
            return False, f"unknown tool {name}, available: {', '.join(self._owner)}"
        if not isinstance(args, dict):
            return False, f"arguments must be a JSON object, got {args!r}"
        future = asyncio.run_coroutine_threadsafe(client.call_tool(name, args), self._loop)
        try:
            result = future.result(CALL_TIMEOUT)
        except KeyboardInterrupt:
            future.cancel()
            raise
        except TimeoutError:
            future.cancel()
            return False, f"{name} took more than {CALL_TIMEOUT}s, gave up"
        except Exception as e:
            return False, f"{name} failed: {e or type(e).__name__}"
        text = result_text(result)
        if result.is_error:
            return False, text or f"{name} failed w/o a msg"
        return True, text

    def capabilities(self):
        """what the model can and cant do w/ its tools, for the system prompt. the tool schemas say
        what each tool does, not what it doesnt cover, so the model would fill gaps from memory"""
        lines = ["Your tools come from these MCP servers:"]
        for name, srv in self.servers.items():
            if srv["status"] != "up":
                lines.append(f"- {name}: down this session, its tools are unavailable.")
                continue
            line = f"- {name} ({', '.join(srv['tools']) or 'no tools'})"
            lines.append(line + (f": {srv['limits']}" if srv["limits"] else ""))
        lines += [
            "Rules:",
            "- Company names, tickers and every number come from a tool result, not from memory.",
            "- If a tool fails, say which one and why, then use another source if there is one.",
        ]
        if any("web_search" in srv["tools"] for srv in self.servers.values()):
            lines += [
                "- When the other tools can't answer (data they don't have, very recent events, unsupported "
                "markets), call web_search before answering, and cite the URLs you used.",
                "- Only say you can't find something once web_search failed or found nothing. Never fill the "
                "gap from memory.",
            ]
        else:
            lines.append("- If no tool covers what is asked, say so and say what is missing. Never fill the gap "
                         "from memory.")
        return "\n".join(lines)

    def close(self):
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
            for task in self._tasks:
                try:
                    task.result(10)
                except Exception:
                    pass  # servers die w/ the process anyway
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        for f in self._logs:
            f.close()
