#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CODEX_HOME=${CODEX_HOME:-"$HOME/.codex"}
BIN_DIR=${BIN_DIR:-"$HOME/.local/bin"}
FAILED=0

remove_skill() {
  name=$1
  expected="$REPO_ROOT/skills/$name"
  target="$CODEX_HOME/skills/$name"
  if [ ! -e "$target" ] && [ ! -L "$target" ]; then
    printf '%s\n' "Skill not installed: $target"
  elif [ -L "$target" ] && [ "$(readlink "$target")" = "$expected" ]; then
    unlink "$target"
    printf '%s\n' "Removed Skill link: $target"
  else
    printf '%s\n' "Refusing to remove Skill not owned by this checkout: $target" >&2
    FAILED=1
  fi
}

remove_wrapper() {
  name=$1
  script_path=$2
  target="$BIN_DIR/$name"
  expected_line="exec python3 \"$script_path\" \"\$@\""
  expected_content=$(printf '%s\n%s' '#!/bin/sh' "$expected_line")
  if [ ! -e "$target" ] && [ ! -L "$target" ]; then
    printf '%s\n' "Command not installed: $target"
  elif [ -f "$target" ] && [ "$(cat "$target")" = "$expected_content" ]; then
    unlink "$target"
    printf '%s\n' "Removed command: $target"
  else
    printf '%s\n' "Refusing to remove command not owned by this checkout: $target" >&2
    FAILED=1
  fi
}

remove_skill agent-os
remove_skill agent-shift
remove_wrapper agent-os "$REPO_ROOT/skills/agent-os/scripts/agent_os.py"
remove_wrapper agent-shift "$REPO_ROOT/skills/agent-shift/scripts/agent_shift.py"

exit "$FAILED"
