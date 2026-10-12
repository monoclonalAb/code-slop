"""Run pi inside a container against a workspace and parse its JSON event stream."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from codeslop import auth
from codeslop import docker
from codeslop.config import ModelSpec

CONTEXT_FILE_RE = re.compile(r"(^|/)(AGENTS(\.override)?\.md|CLAUDE\.md)$")
DOCS_RE = re.compile(r"(^|/)docs/")


@dataclass
class AgentResult:
    exit_code: int
    timed_out: bool
    wall_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd_list_price: float = 0.0
    assistant_messages: int = 0
    tool_calls: int = 0
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    context_file_reads: int = 0  # explicit read/grep/cat of AGENTS.md / CLAUDE.md
    docs_reads: int = 0  # explicit reads of docs/** (manipulation check for the docs arms)
    stop_reason: str | None = None
    error: str | None = None
    final_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _tool_blocks(message: dict):
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") in ("toolCall", "tool_use", "tool_call"):
            yield block.get("name", "?"), block.get("arguments") or block.get("input") or {}


def parse_events(lines: list[str], result: AgentResult) -> list[dict]:
    kept = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message_update":  # streaming deltas: huge, redundant
            kept.append(event)
        if event.get("type") != "message_end":
            continue
        msg = event.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        result.assistant_messages += 1
        usage = msg.get("usage") or {}
        result.input_tokens += int(usage.get("input") or 0)
        result.output_tokens += int(usage.get("output") or 0)
        result.cache_read_tokens += int(usage.get("cacheRead") or 0)
        result.cache_write_tokens += int(usage.get("cacheWrite") or 0)
        result.reasoning_tokens += int(usage.get("reasoning") or 0)
        result.cost_usd_list_price += float((usage.get("cost") or {}).get("total") or 0)
        result.stop_reason = msg.get("stopReason") or result.stop_reason
        if msg.get("errorMessage"):
            result.error = msg["errorMessage"]
        texts = [b.get("text", "") for b in msg.get("content") or []
                 if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            result.final_text = "\n".join(texts)[-4000:]
        for name, args in _tool_blocks(msg):
            result.tool_calls += 1
            result.tool_call_counts[name] = result.tool_call_counts.get(name, 0) + 1
            blob = json.dumps(args)
            path = str(args.get("path") or args.get("file_path") or "")
            if CONTEXT_FILE_RE.search(path) or (name == "bash" and re.search(r"AGENTS\.md|CLAUDE\.md", blob)):
                result.context_file_reads += 1
            if DOCS_RE.search(path) or (name in ("bash", "grep", "find", "ls") and DOCS_RE.search(blob)):
                result.docs_reads += 1
    return kept


def run_pi(workspace: Path, prompt: str, model: ModelSpec, out_dir: Path, *,
           timeout_s: float, provider_cfg: dict, load_context_files: bool = True,
           extra_args: list[str] | None = None) -> AgentResult:
    """One non-interactive pi run in a fresh container. Writes prompt/events/stderr to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.txt").write_text(prompt)
    agent_dir = out_dir / ".pi-agent"
    if agent_dir.exists():
        shutil.rmtree(agent_dir)
    secret_env: dict[str, str] = {}
    copied = None
    if auth.mode(provider_cfg) == "api_key":
        agent_dir.mkdir(parents=True)
        key_env = provider_cfg["api_key_env"]
        secret_env[key_env] = os.environ[key_env]
    else:
        copied = auth.prepare_agent_dir(model.provider, agent_dir,
                                        min_valid_s=timeout_s + 15 * 60,
                                        refresh_model=provider_cfg["refresh_model"])
    cmd = ["pi", "--print", "--mode", "json", "--no-session", "--no-extensions", "--no-skills",
           "--no-prompt-templates", "--provider", model.provider, "--model", model.id,
           "--thinking", model.thinking]
    if not load_context_files:
        cmd.append("--no-context-files")
    cmd += [*(extra_args or []), prompt]

    started = time.time()
    try:
        res = docker.run(cmd, mounts={workspace: "/workspace", agent_dir: "/pi-agent"},
                         secret_env=secret_env, timeout=timeout_s)
    finally:
        if copied is not None:
            auth.sync_back(model.provider, agent_dir, copied)
        shutil.rmtree(agent_dir, ignore_errors=True)  # never keep credentials in run dirs
    result = AgentResult(exit_code=res.returncode, timed_out=res.timed_out,
                         wall_s=round(time.time() - started, 1))
    events = parse_events(res.stdout.splitlines(), result)
    with (out_dir / "agent_events.jsonl").open("w") as fh:
        for e in events:
            fh.write(json.dumps(e, separators=(",", ":")) + "\n")
    (out_dir / "agent_stderr.txt").write_text(res.stderr[-200_000:])
    if res.returncode != 0 and not result.error:
        result.error = (res.stderr.strip().splitlines() or [f"exit {res.returncode}"])[-1][:500]
    (out_dir / "agent.json").write_text(json.dumps(result.to_dict(), indent=2))
    return result
