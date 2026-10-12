"""thin client over the ollama http api, no printing here, errors carry a msg the user can act on"""

import difflib
import json
import os
from urllib.parse import urlparse

import requests

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OllamaError(Exception):
    """base for everything the chat loop shows as a plain msg"""


class Unreachable(OllamaError):
    pass


class AuthError(OllamaError):
    pass


class ModelNotFound(OllamaError):
    pass


class QuotaHit(OllamaError):
    pass


class NotInPlan(OllamaError):
    pass


class Timeout(OllamaError):
    pass


class StreamLost(OllamaError):
    pass


class OllamaClient:
    def __init__(self, host, timeout=120):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.key = os.environ.get("OLLAMA_API_KEY", "").strip()
        self.local = urlparse(self.host).hostname in LOCAL_HOSTS
        if not self.local and not self.key:
            raise AuthError("OLLAMA_API_KEY is missing, set it in .env")
        self.http = requests.Session()
        if self.key and not self.local:
            self.http.headers["Authorization"] = f"Bearer {self.key}"

    def _request(self, method, path, **kw):
        # connect timeout short so a dead host fails fast, read timeout from the cfg
        try:
            r = self.http.request(method, self.host + path, timeout=(10, self.timeout), **kw)
        except requests.ConnectionError:
            raise Unreachable(f"can't reach {self.host}, check the connection") from None
        except requests.Timeout:
            raise Timeout(f"no answer from {self.host} after {self.timeout}s") from None
        if r.status_code in (401, 403):
            raise AuthError("OLLAMA_API_KEY missing or invalid, check .env")
        if r.status_code == 402:
            # listed in /api/tags but paid only, eg the flash ones
            raise NotInPlan("this model isnt in the free tier, pick another one (/model to list them)")
        if r.status_code == 429:
            raise QuotaHit("cloud quota hit, wait for the reset (5h / weekly caps)")
        if r.status_code == 404:
            raise ModelNotFound(_error_text(r) or f"not found: {path}")
        if not r.ok:
            raise OllamaError(f"ollama error {r.status_code}: {_error_text(r) or r.reason}")
        return r

    def check_auth(self):
        """ollama.com /api/tags is public so a bad key only shows on /api/me, local daemon has no auth"""
        if not self.local:
            self._request("POST", "/api/me")

    def list_models(self):
        return sorted(m["name"] for m in self._request("GET", "/api/tags").json().get("models", []))

    def check_model(self, model):
        """raises ModelNotFound w/ the closest names if the model isnt served by this host"""
        names = self.list_models()
        if model in names:
            return
        close = difflib.get_close_matches(model, names, n=3, cutoff=0.4)
        hint = f", closest: {', '.join(close)}" if close else ""
        raise ModelNotFound(f"model {model} not available on {self.host}{hint} (/model to list them)")

    def chat_stream(self, model, messages, tools=None):
        """yields (kind, value) chunk by chunk, kind is "thinking", "content" or "tool_call"

        reasoning models (gpt-oss...) think for seconds before the 1st content token,
        so the thinking is streamed too or the answer looks like 1 block after a pause.
        a tool call comes as 1 complete chunk: {"id", "function": {"name", "arguments": {...}}}
        """
        body = {"model": model, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        r = self._request("POST", "/api/chat", json=body, stream=True)
        try:
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if "error" in data:
                    raise OllamaError(f"ollama error: {data['error']}")
                msg = data.get("message", {})
                if msg.get("thinking"):
                    yield "thinking", msg["thinking"]
                if msg.get("content"):
                    yield "content", msg["content"]
                for call in msg.get("tool_calls") or []:
                    yield "tool_call", call
                if data.get("done"):
                    return
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
            raise StreamLost("connection lost mid answer") from None
        except requests.Timeout:
            raise Timeout(f"answer stalled for more than {self.timeout}s") from None
        except json.JSONDecodeError:
            raise StreamLost("got a broken line from ollama, answer cut") from None
        finally:
            r.close()
        # stream ended w/o done -> server hung up early
        raise StreamLost("connection lost mid answer")


def _error_text(r):
    try:
        return r.json().get("error", "")
    except ValueError:
        return r.text.strip()[:200]
