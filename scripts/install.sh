#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CODEX_HOME=${CODEX_HOME:-"$HOME/.codex"}
BIN_DIR=${BIN_DIR:-"$HOME/.local/bin"}
SKILLS_DIR="$CODEX_HOME/skills"

mkdir -p "$SKILLS_DIR" "$BIN_DIR"

check_skill_target() {
  name=$1
  source_path="$REPO_ROOT/skills/$name"
  target_path="$SKILLS_DIR/$name"
  if [ -L "$target_path" ] && [ "$(readlink "$target_path")" = "$source_path" ]; then
    return
  fi
  if [ -e "$target_path" ] || [ -L "$target_path" ]; then
    printf '%s\n' "Refusing to replace existing Skill: $target_path" >&2
    exit 2
  fi
}

check_wrapper_target() {
  name=$1
  script_path=$2
  target_path="$BIN_DIR/$name"
  expected_content=$(printf '%s\n%s' '#!/bin/sh' "exec python3 \"$script_path\" \"\$@\"")
  if [ -f "$target_path" ] && [ "$(cat "$target_path")" = "$expected_content" ]; then
    return
  fi
  if [ -e "$target_path" ] || [ -L "$target_path" ]; then
    printf '%s\n' "Refusing to replace existing command: $target_path" >&2
    exit 2
  fi
}

install_skill() {
  name=$1
  source_path="$REPO_ROOT/skills/$name"
  target_path="$SKILLS_DIR/$name"

  if [ -L "$target_path" ]; then
    current_target=$(readlink "$target_path")
    if [ "$current_target" = "$source_path" ]; then
      printf '%s\n' "Skill already linked: $target_path"
      return
    fi
    printf '%s\n' "Refusing to replace existing symlink: $target_path" >&2
    exit 2
  fi
  if [ -e "$target_path" ]; then
    printf '%s\n' "Refusing to replace existing Skill: $target_path" >&2
    exit 2
  fi
  ln -s "$source_path" "$target_path"
  printf '%s\n' "Linked Skill: $target_path -> $source_path"
}

install_wrapper() {
  name=$1
  script_path=$2
  target_path="$BIN_DIR/$name"

  expected_line="exec python3 \"$script_path\" \"\$@\""
  expected_content=$(printf '%s\n%s' '#!/bin/sh' "$expected_line")
  if [ -f "$target_path" ] && [ "$(cat "$target_path")" = "$expected_content" ]; then
    chmod 755 "$target_path"
    printf '%s\n' "Command already installed: $target_path"
    return
  fi
  printf '%s\n' '#!/bin/sh' "$expected_line" > "$target_path"
  chmod 755 "$target_path"
  printf '%s\n' "Installed command: $target_path"
}

check_skill_target agent-shift
check_skill_target agent-os
check_wrapper_target agent-shift "$REPO_ROOT/skills/agent-shift/scripts/agent_shift.py"
check_wrapper_target agent-os "$REPO_ROOT/skills/agent-os/scripts/agent_os.py"

install_skill agent-shift
install_skill agent-os
install_wrapper agent-shift "$REPO_ROOT/skills/agent-shift/scripts/agent_shift.py"
install_wrapper agent-os "$REPO_ROOT/skills/agent-os/scripts/agent_os.py"

printf '\n%s\n' "Installation complete. Ensure $BIN_DIR is on PATH, then start a new Codex task so the Skills are rediscovered."
