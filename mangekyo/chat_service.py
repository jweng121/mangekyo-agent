"""Shared model configuration and run-grounded conversations."""

from __future__ import annotations

import json
import os
import base64
import hashlib
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from .store import Store

PROVIDERS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "local": "http://127.0.0.1:11434/v1",
    "custom": "",
}
KEY_ENV = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
_lock = threading.RLock()


@contextmanager
def _session_write_lock(home: Path):
    """Serialize chat writes across terminal and dashboard processes."""
    home.mkdir(parents=True, exist_ok=True)
    with (home / "chat-sessions.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Chat history is busy; try again")
                    time.sleep(.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _config_file(home: Path) -> Path:
    return home / "debug-model.json"


def _sessions_file(home: Path) -> Path:
    return home / "chat-sessions.json"


def _write_private(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


def model_config(home: Path) -> dict | None:
    path = _config_file(home)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def openrouter_auth_url(verifier: str, *, callback_url: str | None = None,
                        state: str | None = None) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    parameters = {"code_challenge": challenge, "code_challenge_method": "S256",
                  "key_label": "Mangekyo Agent"}
    if callback_url:
        if not callback_url.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
            raise ValueError("OAuth callback must use HTTPS or localhost")
        parameters["callback_url"] = callback_url
    if state:
        parameters["state"] = state
    return "https://openrouter.ai/auth?" + urlencode(parameters)


def exchange_openrouter_code(home: Path, *, code: str, verifier: str, model: str) -> dict:
    if not code or not verifier:
        raise ValueError("Authorization code and verifier are required")
    request = Request("https://openrouter.ai/api/v1/auth/keys",
                      data=json.dumps({"code": code, "code_verifier": verifier,
                                       "code_challenge_method": "S256"}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            key = json.load(response)["key"]
    except HTTPError as exc:
        raise RuntimeError(f"OpenRouter sign-in failed (HTTP {exc.code})") from exc
    except (URLError, KeyError, ValueError) as exc:
        raise RuntimeError("OpenRouter sign-in could not be completed") from exc
    return save_model_config(home, provider="openrouter", model=model, api_key=key)


def save_model_config(home: Path, *, provider: str, model: str, base_url: str | None = None,
                      api_key: str | None = None, key_env: str | None = None,
                      no_auth: bool = False) -> dict:
    previous = model_config(home)
    if provider not in PROVIDERS:
        raise ValueError("Choose openai, openrouter, local, or custom")
    model = model.strip()
    if not model:
        raise ValueError("A model name is required")
    url = (base_url or PROVIDERS[provider]).rstrip("/")
    if not url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Use HTTPS, or an HTTP endpoint on localhost")
    if provider in {"openai", "openrouter"} and url != PROVIDERS[provider]:
        raise ValueError("Choose custom for an alternate endpoint")
    if no_auth and provider not in {"local", "custom"}:
        raise ValueError("No authentication is available only for local or custom endpoints")
    config = {"provider": provider, "model": model, "base_url": url,
              "key_env": key_env or KEY_ENV.get(provider), "key_source": "environment",
              "verified": False}
    if no_auth:
        config["key_env"] = None
        config["key_source"] = "none"
    elif api_key:
        try:
            import keyring
            keyring.set_password("mangekyo-agent", str(home.resolve()), api_key)
        except Exception as exc:
            raise RuntimeError("Could not save the API key in the OS credential store; use an environment variable instead") from exc
        config["key_source"] = "keyring"
    elif (previous and previous["provider"] == provider and previous["base_url"] == url and
          previous.get("key_source") == "keyring" and not key_env):
        config["key_source"] = "keyring"
    elif provider in {"openai", "openrouter"} and not config["key_env"]:
        raise ValueError("An API key or environment variable is required")
    _write_private(_config_file(home), config)
    return config


def _api_key(home: Path, config: dict) -> str | None:
    if config["key_source"] == "keyring":
        try:
            import keyring
            return keyring.get_password("mangekyo-agent", str(home.resolve()))
        except Exception as exc:
            raise RuntimeError("Could not read the API key from the OS credential store") from exc
    return os.environ.get(config.get("key_env") or "") or None


def _completion(home: Path, config: dict, messages: list[dict]) -> str:
    key = _api_key(home, config)
    if config["provider"] in {"openai", "openrouter"} and not key:
        raise RuntimeError(f"Missing {config['key_env']} or saved API key")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = Request(config["base_url"] + "/chat/completions",
                      data=json.dumps({"model": config["model"], "messages": messages}).encode(),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=90) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Model endpoint returned HTTP {exc.code}; check provider, model, and credentials") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot connect to model endpoint: {exc.reason}") from exc
    try:
        content = result["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty model response")
        return content.strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("Model endpoint returned an unsupported chat response") from exc


def test_model(home: Path) -> str:
    config = model_config(home)
    if not config:
        raise RuntimeError("No debugging model configured")
    return _completion(home, config, [{"role": "user", "content": "Reply with OK."}])


def verify_model(home: Path) -> str:
    reply = test_model(home)
    config = model_config(home)
    config["verified"] = True
    _write_private(_config_file(home), config)
    return reply


def _run_context(store: Store, run_id: str) -> str:
    run = store.one("runs", run_id)
    events = store.events(run_id)
    lines = [f"Run {run_id}: {run['label']} ({run['status']})"]
    for event in events[-60:]:
        lines.append(f"Event {event['seq']} {event['kind']}: " +
                     json.dumps(event["payload"], ensure_ascii=False, default=str)[:700])
        if event["snapshot_id"]:
            lines.append("Checkpoint: " + json.dumps(store.context(event["snapshot_id"]),
                                                    ensure_ascii=False, default=str)[:2400])
    for artifact in store.artifacts(run_id):
        if artifact["parsed_hash"]:
            lines.append(f"Evidence {artifact['name']}: " +
                         str(store.get(artifact["parsed_hash"])["text"])[:3500])
    return "\n".join(lines)[-22000:]


def sessions(home: Path) -> list[dict]:
    path = _sessions_file(home)
    with _lock:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def ask(home: Path, prompt: str, *, session_id: str | None = None,
        run_id: str | None = None) -> dict:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Enter a question")
    config = model_config(home)
    if not config:
        raise RuntimeError("No debugging model configured; run mangekyo chat to set one up")
    if not config.get("verified"):
        raise RuntimeError("Model connection has not passed its test; run mangekyo model")
    with _lock:
        all_sessions = sessions(home)
        session = next((item for item in all_sessions if item["id"] == session_id), None)
        if session_id and session is None:
            raise ValueError("Chat session not found")
        if session is None:
            session = {"id": uuid.uuid4().hex, "run_id": run_id, "messages": []}
            all_sessions.append(session)
        elif run_id is not None:
            session["run_id"] = run_id
        selected_run = session.get("run_id")
        history = list(session["messages"][-20:])
    context = ""
    if selected_run:
        with Store(home) as store:
            context = _run_context(store, selected_run)
    system = ("You are Mangekyo's debugging assistant. Use the supplied run trace and evidence. "
              "Identify uncertainty. Suggest concrete deterministic eval cases, but never claim an eval "
              "passed unless the recorded eval result says so. Do not invent events or PDF text.\n" + context)
    reply = _completion(home, config, [{"role": "system", "content": system},
                                        *history, {"role": "user", "content": prompt}])
    with _lock, _session_write_lock(home):
        all_sessions = sessions(home)
        session = next((item for item in all_sessions if item["id"] == session["id"]), session)
        if session not in all_sessions:
            all_sessions.append(session)
        session["run_id"] = selected_run
        session["messages"].extend([{"role": "user", "content": prompt},
                                    {"role": "assistant", "content": reply}])
        _write_private(_sessions_file(home), all_sessions)
    return {"session": session["id"], "run_id": selected_run, "reply": reply,
            "messages": session["messages"]}
