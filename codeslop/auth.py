"""pi OAuth credential handling.

Agents run in containers with a *copy* of one provider's OAuth entry from the host's
~/.pi/agent/auth.json. pi only refreshes a token once it has expired, and providers may rotate
refresh tokens on refresh. If a container refreshed mid-run, the host copy could be invalidated.

Strategy:
  1. Before launching a container, make sure the host token stays valid for the whole run. If not,
     force a refresh on the host (temp agent dir with `expires=0`, one trivial pi call), then
     compare-and-swap the new entry back into the host auth.json under pi's own lock.
  2. After the container exits, if it refreshed anyway, CAS its new entry back to the host.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

HOST_AUTH = Path(os.environ.get("CODESLOP_PI_AUTH", Path.home() / ".pi" / "agent" / "auth.json"))
_THREAD_LOCK = threading.Lock()


def _expires_s(entry: dict) -> float:
    e = float(entry.get("expires", 0))
    return e / 1000 if e > 1e12 else e


@contextmanager
def _pi_lock(path: Path, timeout: float = 30.0):
    """Same mkdir-based lock that proper-lockfile (used by pi) takes on auth.json."""
    lock = Path(f"{path}.lock")
    deadline = time.time() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 30:  # stale (pi updates mtime while held)
                shutil.rmtree(lock, ignore_errors=True)
                continue
            if time.time() > deadline:
                raise TimeoutError(f"could not lock {path}")
            time.sleep(0.2)
    try:
        yield
    finally:
        shutil.rmtree(lock, ignore_errors=True)


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".codeslop.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def mode(provider_cfg: dict) -> str:
    """'api_key' or 'oauth' for a provider config from models.yaml."""
    wanted = provider_cfg.get("auth", "oauth")
    key_env = provider_cfg.get("api_key_env")
    if wanted == "api_key":
        if not key_env or not os.environ.get(key_env):
            raise RuntimeError(f"auth=api_key but ${key_env or '<api_key_env unset>'} is not set")
        return "api_key"
    if wanted == "auto" and key_env and os.environ.get(key_env):
        return "api_key"
    return "oauth"


def host_entry(provider: str) -> dict:
    entry = _read(HOST_AUTH).get(provider)
    if not entry:
        raise RuntimeError(f"no pi login for provider '{provider}' in {HOST_AUTH} (run `pi` and /login)")
    return entry


def hours_left(provider: str) -> float:
    return (_expires_s(host_entry(provider)) - time.time()) / 3600


def _cas_write(provider: str, expected_refresh: str | None, new_entry: dict) -> bool:
    """Write new_entry iff the host still holds the refresh token we started from."""
    with _pi_lock(HOST_AUTH):
        data = _read(HOST_AUTH)
        current = data.get(provider, {})
        if current.get("refresh") != expected_refresh:
            return False  # host refreshed independently; keep host's (newer) entry
        backup = HOST_AUTH.with_name("auth.json.codeslop.bak")
        if not backup.exists():
            shutil.copy2(HOST_AUTH, backup)
        data[provider] = new_entry
        _atomic_write(HOST_AUTH, data)
        return True


def force_refresh(provider: str, refresh_model: str) -> None:
    entry = host_entry(provider)
    with tempfile.TemporaryDirectory(prefix="codeslop-auth-") as tmp:
        tmp_auth = Path(tmp) / "auth.json"
        _atomic_write(tmp_auth, {provider: {**entry, "expires": 0}})
        env = {**os.environ, "PI_CODING_AGENT_DIR": tmp}
        cmd = ["pi", "--print", "--no-session", "--no-tools", "--no-extensions", "--no-skills",
               "--no-prompt-templates", "--no-context-files", "--provider", provider,
               "--model", refresh_model, "Reply with OK."]
        proc = subprocess.run(cmd, env=env, cwd=tmp, capture_output=True, text=True, timeout=120)
        new = _read(tmp_auth).get(provider, {})
        if proc.returncode != 0 or _expires_s(new) <= time.time():
            raise RuntimeError(f"token refresh failed for {provider}: {proc.stderr[-500:]}")
        _cas_write(provider, entry.get("refresh"), new)


def prepare_agent_dir(provider: str, agent_dir: Path, *, min_valid_s: float,
                      refresh_model: str) -> dict:
    """Write an isolated pi config dir holding only this provider's credentials.

    Returns the entry that was copied (needed for sync_back)."""
    with _THREAD_LOCK:
        if _expires_s(host_entry(provider)) - time.time() < min_valid_s:
            force_refresh(provider, refresh_model)
        entry = host_entry(provider)
    agent_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(agent_dir / "auth.json", {provider: entry})
    return entry


def sync_back(provider: str, agent_dir: Path, copied: dict) -> None:
    new = _read(agent_dir / "auth.json").get(provider)
    if new and new.get("refresh") != copied.get("refresh"):
        with _THREAD_LOCK:
            _cas_write(provider, copied.get("refresh"), new)
