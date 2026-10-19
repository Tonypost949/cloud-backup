#!/usr/bin/env bash
# cloud_backup.sh — Universal multi-cloud backup executor (Google GCS + Microsoft OneDrive + extensible)
# Part of the OsintNeoAi/Antigravity stack. Directions: README.md in this folder.
# Ledger: ~/tools/task_system/backup_ledger.jsonl   |   Registry: storage_nodes.csv
#
# Usage:
#   cloud_backup.sh push <set>               # backup a named set to ALL configured targets
#   cloud_backup.sh push-path <path> [label]
#   cloud_backup.sh sets                     # list sets
#   cloud_backup.sh targets                  # show configured targets
#   cloud_backup.sh verify <set>             # rclone check against GCS
# Sets: critical daily tools heretic mirrors all
set -uo pipefail

RCLONE="${RCLONE_BIN:-$HOME/tools/bin/rclone}"
[ -x "$RCLONE" ] || RCLONE="rclone"
GCS_BUCKET="${GCS_BUCKET:-backup-project-743aab84-f9a5-4ec7-954}"
GCS_ROOT="${GCS_ROOT:-osintneoai_azure_vm}"
OD_ROOT="${OD_ROOT:-Backups/osintneoai_azure_vm}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MACHINE="$(hostname -s 2>/dev/null || hostname)"
TASKS="${TASKS_DIR:-$HOME/tools/task_system}"
LEDGER="$TASKS/backup_ledger.jsonl"
EXCL=(--exclude ".venv/**" --exclude "**/.venv/**" --exclude "venv/**" --exclude "**/__pycache__/**" --exclude "*.pyc")

# --- GCS token self-heal (2026-10-19): a stale access token with a future
# stored expiry blocks rclone's auto-refresh (401 Invalid Credentials).
# Normalizing the expiry to the past forces rclone to refresh from the
# stored refresh_token on the next call and persist a correct expiry.
heal_gcs_token() {
  python3 - "$RCLONE" <<'PY'
import json, subprocess, sys
R = sys.argv[1]
dump = json.loads(subprocess.run([R, "config", "dump"], capture_output=True, text=True).stdout or "{}")
if "gcs" not in dump:
    sys.exit(0)
t = json.loads(dump["gcs"].get("token", "{}"))
t["expiry"] = "2000-01-01T00:00:00Z"
subprocess.run([R, "config", "update", "gcs", "token", json.dumps(t), "--non-interactive"],
               capture_output=True, text=True)
PY
}

preflight() {
  if ! "$RCLONE" lsd gcs: --max-depth 1 >/dev/null 2>&1; then
    echo "WARN: gcs check failed — forcing token refresh" >&2
    heal_gcs_token
    "$RCLONE" lsd gcs: --max-depth 1 >/dev/null 2>&1 \
      || echo "WARN: gcs still unreachable — this run may record partial" >&2
  fi
}

targets() {
  echo "gcs:$GCS_BUCKET/$GCS_ROOT/$MACHINE"
  if "$RCLONE" listremotes 2>/dev/null | grep -qx "onedrive:"; then
    echo "onedrive:$OD_ROOT/$MACHINE"
  fi
}

entries() {
  case "$1" in
    critical)
      echo "laws|$HOME/00_ailaws.md"
      echo "laws-agents|$HOME/AGENTS.md"
      echo "laws-skill|$HOME/.agents/skills/ailaws"
      echo "tasksystem|$TASKS"
      echo "keys|$HOME/Amd949609_keys"
      echo "onedrive-auth|$HOME/.config/onedrive"
      echo "rclone-conf|$HOME/.config/rclone/rclone.conf"
      ;;
    daily)
      echo "laws|$HOME/00_ailaws.md"
      echo "tasksystem|$TASKS"
      echo "keys|$HOME/Amd949609_keys"
      ;;
    tools)
      echo "heretic|$HOME/tools/heretic"
      echo "auto_kali|$HOME/tools/auto_kali"
      echo "revolver|$HOME/tools/github_revolver"
      echo "cloud_backup|$HOME/tools/cloud_backup"
      echo "bin|$HOME/tools/bin"
      ;;
    heretic)
      echo "heretic-runs|$HOME/tools/heretic/runs"
      echo "heretic-models|$HOME/tools/heretic/models"
      ;;
    mirrors)
      echo "github-mirrors|$HOME/backups/github_mirrors"
      ;;
    all)
      entries critical; entries tools; entries heretic
      ;;
    *)
      echo "UNKNOWN SET: $1" >&2; return 2 ;;
  esac
}

push_one() {
  local label="$1" src="$2" ok="ok"
  [ -e "$src" ] || { echo "SKIP (missing): $src"; return 0; }
  local dests; dests="$(targets | tr '\n' ' ')"
  local t
  for t in $(targets); do
    local dest="$t/$STAMP/$label"
    echo "==> [$label] $src -> $dest"
    if ! "$RCLONE" copy "$src" "$dest" "${EXCL[@]}" --transfers 6 --checkers 12 --stats-one-line --stats 20s; then
      ok="partial"
    fi
  done
  printf '{"ts":"%s","machine":"%s","label":"%s","src":"%s","targets":"%s","status":"%s","tool":"cloud_backup.sh"}\n' \
    "$STAMP" "$MACHINE" "$label" "$src" "$dests" "$ok" >> "$LEDGER"
}

case "${1:-help}" in
  push)
    [ $# -eq 2 ] || { echo "usage: cloud_backup.sh push <set>"; exit 2; }
    preflight
    while IFS='|' read -r label src; do push_one "$label" "$src"; done < <(entries "$2")
    ;;
  push-path)
    [ $# -ge 2 ] || { echo "usage: cloud_backup.sh push-path <path> [label]"; exit 2; }
    push_one "${3:-adhoc}" "$2"
    ;;
  sets) echo "critical daily tools heretic mirrors all" ;;
  targets) targets ;;
  verify)
    [ $# -eq 2 ] || { echo "usage: cloud_backup.sh verify <set>"; exit 2; }
    while IFS='|' read -r label src; do
      echo "-- $label"
      "$RCLONE" check "$src" "gcs:$GCS_BUCKET/$GCS_ROOT/$MACHINE" --one-way 2>&1 | tail -2
    done < <(entries "$2")
    ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
