#!/usr/bin/env bash
# Pre-completion audit: GPT-6 Astra (xhigh thinking) reviews a task's changes
# read-only and prints its findings. Policy and steps: AGENTS.md
# ("Pre-completion audit"). Ported from the beacon repository.
set -euo pipefail

MODEL="openai-codex/gpt-6-astra"
THINKING="xhigh"
MAX_DIFF_BYTES=600000 # ~150k tokens; leaves room in Astra's 272k window

usage() {
  cat <<'EOF'
Usage: bash scripts/audit-changes.sh [--base <ref>] [--dry-run] "<what the task asked for>"

Audits the changes between <ref> (default HEAD) and the working tree, including
staged, unstaged and untracked files. Pass --base when the task's work is
already committed. --dry-run prints what would be sent and stops.

Exit: 0 VERDICT: PASS, 3 VERDICT: FIX, 1 audit failed or gave no verdict, 2 usage.
EOF
}

base="HEAD" dry_run=0 task=""
while (($#)); do
  case "$1" in
    --base) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; base="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *) [[ -z "$task" ]] || { usage >&2; exit 2; }; task="$1"; shift ;;
  esac
done
[[ -n "$task" ]] || { usage >&2; exit 2; }

cd "$(git rev-parse --show-toplevel)"
git rev-parse --verify --quiet "${base}^{commit}" >/dev/null \
  || { echo "audit: unknown ref '$base'" >&2; exit 2; }

# Lockfile bodies are noise for review; the file list below still names them.
pathspec=(-- . ':(exclude)uv.lock')
untracked=()
while IFS= read -r -d '' file; do untracked+=("$file"); done \
  < <(git ls-files -z --others --exclude-standard)

if git diff --quiet "$base" -- && ((${#untracked[@]} == 0)); then
  echo "audit: no changes since $base; nothing to audit"
  exit 0
fi

diff_file="$(mktemp -t codeslop-audit-diff.XXXXXX)"
payload="$(mktemp -t codeslop-audit.XXXXXX)"
trap 'rm -f "$diff_file" "$payload"' EXIT
{
  git diff --no-color "$base" "${pathspec[@]}"
  for file in ${untracked[@]+"${untracked[@]}"}; do
    case "$file" in *uv.lock) continue ;; esac
    echo "## untracked file: $file"
    git diff --no-color --no-index -- /dev/null "$file" || true
  done
} >"$diff_file"
diff_bytes=$(wc -c <"$diff_file" | tr -d ' ')

{
  echo "# Changes to audit (base: $base)"
  echo
  echo "## git status --short"
  git status --short
  echo
  echo "## Every changed file since $base, lockfiles included"
  git diff --name-status "$base" --
  for file in ${untracked[@]+"${untracked[@]}"}; do printf '??\t%s\n' "$file"; done
  echo
  echo "## Diff (lockfile bodies left out, untracked files at the end)"
  if ((diff_bytes <= MAX_DIFF_BYTES)); then
    cat "$diff_file"
  else
    echo "audit: diff is $diff_bytes bytes; Astra reads it from a file" >&2
    echo "The diff is $diff_bytes bytes, too large to include here. Read all of"
    echo "it in chunks with the read tool (offset and limit) from: $diff_file"
  fi
} >"$payload"
bytes=$(wc -c <"$payload" | tr -d ' ')

prompt="You are the pre-completion auditor for the code-slop repository. Another
agent made the changes above and is about to report its task complete; it will
fix what you find. You are read-only (read, grep, find, ls). You are the audit
that AGENTS.md asks for, so do not try to run it.

What the task asked for: ${task}

Read the surrounding code and the owning docs (README.md, AUDIT.md,
arms/README.md) when you need context. Look for:
- bugs, regressions and unhandled failure cases in the harness;
- work the task asked for that is missing, and changes it did not ask for;
- breaks of AGENTS.md rules, of the pinned versions in README.md, or of the
  arm-authoring rules in arms/README.md (no foresight past the start checkpoint,
  never teaching scb-check rules);
- docs or the arm index that now disagree with the code;
- missing or weak verification for what changed;
- secrets, credentials or production data in the diff.

Report only real, specific problems, most severe first. For each give the
severity (high, medium or low), file:line, what is wrong, why it matters, and
the fix. No praise and no style nits. End with exactly one line: VERDICT: PASS
when nothing needs fixing, otherwise VERDICT: FIX."

if ((dry_run)); then
  cat "$payload"
  echo "audit: dry run; would send $bytes bytes of changes since $base to $MODEL ($THINKING)"
  exit 0
fi
command -v pi >/dev/null || { echo "audit: 'pi' is not on PATH" >&2; exit 1; }

echo "audit: sending $bytes bytes of changes since $base to $MODEL ($THINKING); this can take several minutes" >&2
# Unset Herdr variables so the nested Pi cannot retitle this agent's pane.
report="$(env -u HERDR_ENV -u HERDR_PANE_ID -u HERDR_SOCKET_PATH \
  pi --print --model "$MODEL" --thinking "$THINKING" --no-session --no-mcp \
  --tools read,grep,find,ls "$prompt" <"$payload")" \
  || { printf '%s\n' "$report"; echo "audit: pi exited with an error" >&2; exit 1; }
printf '%s\n' "$report"

verdict="$(printf '%s\n' "$report" | grep -E '^[[:space:]*`]*VERDICT: (PASS|FIX)' | tail -n 1 || true)"
case "$verdict" in
  *"VERDICT: PASS"*) exit 0 ;;
  *"VERDICT: FIX"*) exit 3 ;;
  *) echo "audit: no VERDICT line in the report" >&2; exit 1 ;;
esac