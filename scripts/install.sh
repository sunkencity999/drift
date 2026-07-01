#!/usr/bin/env bash
# Drift — cross-platform, user-level installer. Mirrors Mechanic's installer.
#
#   1. Detects macOS / Linux, checks prerequisites (python3.11+, git, pip).
#   2. Creates a venv under the install prefix and pip-installs Drift (-e).
#   3. Writes a default config (~/.config/drift/drift.ini) with data_dir set.
#   4. Installs a USER-LEVEL supervisor for the snapshotter daemon:
#        macOS  -> ~/Library/LaunchAgents/dev.drift.snapshotter.plist  (launchctl load)
#        Linux  -> ~/.config/systemd/user/drift-snapshotter.service    (systemctl --user enable --now)
#      (The MCP *server* is launched on-demand by the AI client — no supervisor needed.)
#   5. Offers to wire Drift into the Claude Code MCP config (~/.claude.json),
#      idempotently, with a timestamped backup first.
#   6. Runs `drift doctor` to summarize what's working.
#
# No sudo required. No backticks in heredocs (they execute as command substitution).

set -euo pipefail

if [[ -t 1 ]]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'
  BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; DIM=''; NC=''
fi

log()  { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${NC} %s\n" "$*" >&2; }
err()  { printf "${RED}✗${NC} %s\n" "$*" >&2; }
info() { printf "${DIM}%s${NC}\n" "$*"; }
hdr()  { printf "\n${BLUE}╶─${NC} %s\n" "$*"; }

PREFIX="${DRIFT_PREFIX:-$HOME/.local}"
INSTALL_DIR="${DRIFT_INSTALL_DIR:-$PREFIX/share/drift}"
VENV_DIR="${DRIFT_VENV_DIR:-$INSTALL_DIR/.venv}"
BIN_LINK="$PREFIX/bin/drift"
CONFIG_DIR="${DRIFT_CONFIG_DIR:-$HOME/.config/drift}"
DATA_DIR="${DRIFT_DATA_DIR:-$PREFIX/share/drift-data}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_CLAUDE_WIRE="${DRIFT_SKIP_CLAUDE_WIRE:-0}"

hdr "Drift installer"

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macos";;
  Linux)   PLATFORM="linux";;
  *) err "Unsupported OS: $OS (need macOS or Linux)"; exit 1;;
esac
log "Detected platform: $PLATFORM"

PYOK=0
if command -v python3 >/dev/null 2>&1; then
  PYV="$(python3 -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo 0)"
  PYMAJOR="${PYV%%.*}"; PYMINOR="${PYV#*.}"
  if [[ "$PYMAJOR" -gt 3 || ( "$PYMAJOR" -eq 3 && "$PYMINOR" -ge 11 ) ]]; then
    PYOK=1
  fi
fi
if [[ "$PYOK" -ne 1 ]]; then
  err "Python 3.11+ required (found: ${PYV:-none})"
  exit 2
fi
log "Python: $PYV"

for dep in git; do
  if ! command -v "$dep" >/dev/null 2>&1; then
    err "Missing required command: $dep"
    exit 2
  fi
done
log "git present"

if ! command -v pip >/dev/null 2>&1; then
  if ! python3 -m pip --version >/dev/null 2>&1; then
    err "pip not found (need pip or python3 -m pip)"
    exit 2
  fi
fi
log "pip present"

hdr "Installing into $VENV_DIR"
mkdir -p "$INSTALL_DIR" "$PREFIX/bin"
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/python" -m pip install --quiet -e "$REPO_ROOT"
log "Drift installed into venv"

cat > "$BIN_LINK" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/drift" "\$@"
EOF
chmod +x "$BIN_LINK"
log "CLI shim: $BIN_LINK"
if [[ ":$PATH:" != *":$PREFIX/bin:"* ]]; then
  warn "$PREFIX/bin is not on your PATH — add it to your shell rc, or use $BIN_LINK directly."
fi

hdr "Configuration"
mkdir -p "$CONFIG_DIR"
INI="$CONFIG_DIR/drift.ini"
if [[ ! -f "$INI" ]]; then
  cat > "$INI" <<EOF
# Drift configuration. All values optional; defaults shown.
[snapshotter]
interval_hours = 6
retention_snapshots = 240

[storage]
# The single source of truth for where snapshots live. The daemon, the MCP server,
# and your interactive 'drift list' all read this, so they agree on one DB.
data_dir = $DATA_DIR
EOF
  log "Wrote default config: $INI"
else
  log "Existing config preserved: $INI"
  warn "If its [storage] data_dir doesn't match $DATA_DIR, the CLI and daemon may use different DBs."
fi
mkdir -p "$DATA_DIR"
log "Data dir: $DATA_DIR"

hdr "Supervisor (snapshotter daemon)"
SVC_NAME="drift-snapshotter"
if [[ "$PLATFORM" == "macos" ]]; then
  PLIST="$HOME/Library/LaunchAgents/dev.drift.snapshotter.plist"
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.drift.snapshotter</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_DIR/bin/drift</string>
    <string>snapshotter</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DRIFT_DATA_DIR</key><string>$DATA_DIR</string>
    <key>PATH</key><string>$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DATA_DIR/snapshotter.log</string>
  <key>StandardErrorPath</key><string>$DATA_DIR/snapshotter.err.log</string>
</dict>
</plist>
EOF
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  launchctl load   "$PLIST" >/dev/null 2>&1
  log "launchd agent installed + loaded: $PLIST"
  info "(logs: $DATA_DIR/snapshotter.log)"
else
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  UNIT="$UNIT_DIR/$SVC_NAME.service"
  cat > "$UNIT" <<EOF
[Unit]
Description=Drift snapshotter daemon
After=network.target

[Service]
Type=simple
ExecStart=$VENV_DIR/bin/drift snapshotter
Environment=DRIFT_DATA_DIR=$DATA_DIR
Restart=on-failure
RestartSec=10
StandardOutput=append:$DATA_DIR/snapshotter.log
StandardError=append:$DATA_DIR/snapshotter.err.log

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$SVC_NAME" >/dev/null 2>&1
  log "systemd --user unit installed + enabled: $UNIT"
  info "(logs: $DATA_DIR/snapshotter.log)"
  loginctl enable-linger "$USER" 2>/dev/null || true
fi

hdr "AI client wiring"
CLAUDE_JSON="$HOME/.claude.json"
wire_claude() {
  if [[ ! -f "$CLAUDE_JSON" ]]; then
    warn "~/.claude.json not found — skipping Claude Code wiring."
    info "When you install Claude Code, re-run this script or add the server manually:"
    info "  drift server  (as an stdio MCP server)"
    return
  fi
  cp "$CLAUDE_JSON" "$CLAUDE_JSON.drift-bak.$(date +%Y%m%d%H%M%S)"
  "$VENV_DIR/bin/python" - <<PYEOF
import json, os
path = os.path.expanduser("$CLAUDE_JSON")
with open(path) as f:
    cfg = json.load(f)
mcp = cfg.setdefault("mcpServers", {})
venv = "$VENV_DIR"
mcp["drift"] = {
    "type": "stdio",
    "command": f"{venv}/bin/drift",
    "args": ["server"],
    "env": {"DRIFT_DATA_DIR": "$DATA_DIR"},
}
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
print("✓ wired 'drift' server into ~/.claude.json")
PYEOF
}

if [[ "$SKIP_CLAUDE_WIRE" == "1" ]]; then
  info "Claude wiring skipped (DRIFT_SKIP_CLAUDE_WIRE=1)"
else
  wire_claude
fi

hdr "Health check"
"$VENV_DIR/bin/drift" doctor || true

printf "\n${BOLD}Done.${NC} Drift is snapshotting in the background every 6h.\n"
info "Next: restart your AI client so it picks up the 'drift' MCP server, then ask:"
info "  \"use drift — what changed on this box recently?\""
info "Uninstall: scripts/uninstall.sh"
