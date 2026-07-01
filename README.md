# Drift

> A `diff` for live systems. Snapshot a box's operational state, then ask **"what changed, in plain English?"** — over MCP.

```
   you come back from PTO ──┐
                            ▼
            ┌───────────────────────────────┐
            │ "what did the intern touch     │
            │  on this box since Tuesday?"   │
            └───────────────┬───────────────┘
                            │ MCP (stdio)
                ┌───────────▼───────────┐
                │   drift server          │  ← spawns on demand
                │  (diff, latest,         │
                │   list_snapshots, doctor)│
                └───────────┬───────────┘
                            │ reads
                ┌───────────▼───────────┐
                │   drift.sqlite          │  ← snapshots (JSON)
                └───────────▲───────────┘
                            │ writes every 6h (+ manual)
                ┌───────────┴───────────┐
                │   drift snapshotter     │  ← launchd / systemd --user
                │  (ports, services,     │     auto-prune keeps the last N
                │   packages, users, cron)│
                └───────────────────────┘
```

## What & why

You come back from a week off. Something on the box is different — a port is open that wasn't, a package appeared, a service is enabled, a user was added. *What changed?*

Your existing tools answer every question *except* that one:

- **`etckeeper`** watches `/etc` files. It doesn't see runtime state (ports, running services, installed packages on a non-declaring system).
- **AIDE / Tripwire** do file integrity for *security*. They're not for "what did someone configure differently?"
- **Ansible** defines *desired* state — but only what *you* declared. It won't tell you what drifted outside your playbook.
- **`btop` / `glances`** show right now. They don't remember, and they don't diff.

Drift is the missing one: it snapshots the **observed operational state** of a box at intervals, and **diffs two snapshots** to tell you, in plain English, what moved. Port 9000 opened. `nginx` was installed. `ssh.service` was enabled. User `bob` was added.

It is:

- **Local-first.** Snapshots live in `~/.local/share/drift-data/`. No cloud, no egress.
- **MCP-native.** Ask your AI client "what changed?" and it calls Drift's `diff` tool.
- **User-level.** No `sudo`. Runs under your own launchd / systemd --user.
- **Bounded.** Auto-prune keeps only the most recent N snapshots (default 240 ≈ 10 days @ 6h). Manual labeled snapshots are exempt — never pruned.
- **Runs anywhere.** macOS and Linux. Collectors no-op gracefully when their backend isn't installed.

## Drift × Mechanic — use them together

Drift is the companion to [**Mechanic**](https://github.com/sunkencity999/mechanic), and they're most powerful as a pair:

- **Mechanic** watches *runtime metrics* continuously (CPU, memory, Ollama models loaded, Docker containers) and tells you **the numbers moved** — "CPU is anomalous right now."
- **Drift** watches *operational configuration* at intervals (ports, services, packages, users, cron) and tells you **what configuration moved** — "port 9000 was opened 2 hours ago."

**The workflow:** Mechanic flags that something is off → ask Drift what changed between now and the last snapshot → Drift shows the config change that explains it. A CPU spike (Mechanic) + a newly-enabled service (Drift) = the full story. Each is useful alone; together they cover "is this abnormal?" *and* "what changed?".

## Quickstart

```bash
bash scripts/install.sh
```

Installs Drift into a venv under `~/.local/share/drift`, starts the snapshotter daemon (every 6h, auto-prune to 240 snapshots), and wires it into Claude Code's MCP config. Then restart your AI client and ask:

> *"Use drift — what changed on this box between the two most recent snapshots?"*

Or, without any AI client:

```bash
drift snap --label before-deploy    # take a manual, labeled snapshot
# ... do the deploy ...
drift snap --label after-deploy
drift diff before-deploy after-deploy   # plain-English summary
drift diff before-deploy after-deploy --json   # structured JSON
drift list                          # recent snapshots
drift doctor                        # collector availability + storage health
```

## Install

### One-liner (from a checkout)

```bash
bash scripts/install.sh
```

### Overridable knobs (env vars)

| Variable | Default | What |
|---|---|---|
| `DRIFT_PREFIX` | `$HOME/.local` | where the venv + bin shim live |
| `DRIFT_INSTALL_DIR` | `$PREFIX/share/drift` | venv parent |
| `DRIFT_CONFIG_DIR` | `$HOME/.config/drift` | `drift.ini` location |
| `DRIFT_DATA_DIR` | `$PREFIX/share/drift-data` | SQLite + logs |
| `DRIFT_SKIP_CLAUDE_WIRE` | `0` | set `1` to skip editing `~/.claude.json` |

### Uninstall

```bash
bash scripts/uninstall.sh          # stops daemon, removes install, keeps data + config
bash scripts/uninstall.sh --purge  # also removes data + config
```

## The MCP tools

These are what your AI client sees. All read-only, all return JSON.

### `diff(snapshot_a, snapshot_b)`
Compare two snapshots. Each argument is a snapshot id (int) or label (resolved to the latest with that label). Returns a structured `diff` (added/removed/changed per collector) AND a plain-English `summary` string.
```json
{"snapshot_a": {"id": 1, "label": "before"}, "snapshot_b": {"id": 2, "label": "after"},
 "diff": {"ports": {"listeners": {"added": [{"port": 8080, "proto": "tcp", "proc": "python"}]}}},
 "summary": "Compared 'before' → 'after'. Changes: ports: 1 port(s) added (8080/tcp)."}
```

### `latest()`
The most recent snapshot (id, ts, label, full payload).

### `list_snapshots(limit)`
Recent snapshots, newest first, with id/ts/label — so the AI can pick which two to diff.

### `doctor()`
Collector availability + storage health (path, schema version, total snapshots). The single source of truth for "is Drift healthy here?"

### Example prompts to try

- *"Use drift — what changed on this box between the two most recent snapshots?"*
- *"Take a drift snapshot labeled 'before-upgrade'."* → (do the upgrade) → *"Now diff 'before-upgrade' against the latest snapshot and tell me what changed."*
- *"List recent drift snapshots. Which two should I compare to see Tuesday's changes?"*
- *"Run drift's doctor tool — what collectors are available?"*
- *"What ports opened or closed on this box recently?"*
- *"Were any packages installed or removed since the last snapshot?"*
- *"Did the set of running services change? Use drift to diff."*
- *"Any new users added to this box since the baseline snapshot?"*

**Tip:** you don't have to know snapshot ids — labels work, and `latest()` / `list_snapshots()` let the AI pick sensible defaults.

## Configuration

`~/.config/drift/drift.ini` (created by the installer with defaults if absent):

```ini
[snapshotter]
interval_hours = 6          # how often the daemon snapshots
retention_snapshots = 240   # keep most recent N; prune older unlabeled ones

[storage]
data_dir = /home/you/.local/share/drift-data   # single source of truth for the DB
```

All values also overridable via env vars (`DRIFT_INTERVAL_HOURS`, `DRIFT_RETENTION_SNAPSHOTS`, `DRIFT_DATA_DIR`, etc.).

### Auto-prune (the important part)

After every snapshot write, Drift prunes: it keeps the **most recent `retention_snapshots` unlabeled** snapshots and deletes older unlabeled ones. **Manual labeled snapshots are exempt** — `drift snap --label before-deploy` will never be silently deleted. This bounds storage for long unattended runs (the explicit design goal) while protecting the snapshots you care about.

## Adding a collector

A collector is one file satisfying a tiny protocol. Drop this in `drift/plugins/`:

```python
# drift/plugins/mything_collector.py
from drift.plugins.base import CollectorError

class MythingCollector:
    name = "mything"

    def is_available(self) -> bool:
        import shutil
        return shutil.which("mything") is not None

    def collect(self) -> dict:
        if not self.is_available():
            raise CollectorError("mything not installed")
        return {"widgets": ["a", "b"]}   # list values diff as sets; numbers as scalars

collector = MythingCollector()
```

That's it. Auto-discovered; `drift doctor` lists it; the snapshotter captures it; the differ compares it. Three rules:

1. **JSON-serializable.** List values become set-diffs (added/removed); numbers become scalar-diffs (from/to/delta).
2. **Fail soft.** Raise `CollectorError` on failure; the snapshotter isolates it and records it in the snapshot's `errors` list. One collector's failure never stops a snapshot.
3. **Normalize across platforms** where it makes sense (ports returns `{proto, port, proc}` whether from `lsof` or `ss`), so diffs are meaningful.

## The v1 collectors

| Collector | macOS source | Linux source | What it captures |
|---|---|---|---|
| `ports` | `lsof` | `ss` | listening TCP ports `{proto, port, proc}` |
| `services` | `launchctl list` | `systemctl list-units` | enabled/running service labels/units |
| `packages` | `brew list` | `dpkg-query` / `rpm` | installed package set + manager |
| `users` | `dscl` | `/etc/passwd` (uid ≥ 1000) | real user accounts |
| `cron` | `crontab -l` + user LaunchAgents | `crontab -l` + `/etc/cron.d` | scheduled jobs |

## Architecture

**Three pieces, one file.**

- **`drift snapshotter`** — the long-running daemon (launchd / systemd --user). Every `interval_hours`, runs all available collectors into one JSON document and writes it to SQLite. Auto-prunes after each write. Clean SIGTERM/SIGINT exit.
- **`drift server`** — the MCP stdio server, spawned on demand by the AI client. A stateless reader: every tool call reads from the store. No in-memory state, no warmup.
- **`drift snap` / `drift diff`** — the interactive CLI. `snap` captures a manual labeled snapshot (prune-exempt); `diff` compares two and prints English or JSON.

**Why snapshots, not a continuous sampler?** Drift is a *different shape* from Mechanic. Operational state (which ports are open, which packages installed) changes in discrete steps, not continuously — a port opens *once*, not "drifts up." So Drift captures point-in-time snapshots and diffs them, rather than sampling a time-series and baselining. No baseline engine, no z-scores — just set and scalar diffs.

**Why SQLite?** One file, zero config, portable. Each snapshot is one row; the differ loads two and compares. If you outgrow it, the store is one module — swap it without touching collectors or the differ.

## Project layout

```
drift/
  README.md
  LICENSE                       # MIT
  pyproject.toml
  drift/
    config.py                   # Config + ini loader (env > ini > defaults)
    store.py                    # SQLite: snapshots + count-based prune (pure I/O)
    snapshot.py                 # aggregates collectors into one JSON doc (glue)
    differ.py                   # diff + summarize — pure functions, the heart
    server.py                   # FastMCP stdio server (stateless reader)
    cli.py                      # `drift` entrypoint + snapshotter daemon
    plugins/
      base.py                   # CollectorPlugin protocol + registry
      ports.py services.py packages.py users.py cron.py
  scripts/
    install.sh uninstall.sh
  tests/                       # pytest; ~85 tests, bottom-up TDD
```

## Security

- No network egress, ever. Every collector reads local state (local processes, local files, `/etc/passwd`).
- All data lives in `~/.local/share/drift-data/drift.sqlite`. Delete the file, delete the history.
- The MCP server is a reader; it cannot mutate the store or run collectors.
- The installer never asks for root. It edits your own `~/.claude.json` with a timestamped backup.

## Roadmap

More collectors in v1.1+ (firewall rules, kernel parameters, environment, systemd unit *state* not just presence), scheduled diff reports, remote aggregation across a homelab, file-content hashing for the etckeeper crowd.

## License

MIT — see `LICENSE`.
