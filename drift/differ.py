"""The diff engine — the heart of Drift.

Pure functions: diff(past, latest) -> structured {added, removed, changed}, and
summarize(diff) -> plain English. No I/O, no state — trivially testable, and the part
of Drift that has to be correct above all.

Per-collector comparison rules:
  - list-valued keys  → set difference (added = new - old, removed = old - new).
    Lists of dicts (e.g. port listeners) are compared by their JSON-serialized form
    so structurally-equal entries match.
  - scalar (number) keys → changed {from, to, delta} when delta != 0.
  - a collector present in only one snapshot → reported in top-level added/removed.

A collector with no changes is omitted from the diff entirely (clean signal).
"""

from __future__ import annotations

import json
from typing import Any

# Keys whose values are sets/lists we diff as sets.
# Heuristic: if a value is a list, treat it as a set. Scalars (int/float) get delta'd.
# Strings/bools are ignored (not meaningfully diffable here).


def diff(past: dict, latest: dict) -> dict[str, Any]:
    """Compare two snapshot documents. Returns structured diff.

    Top-level keys:
      "<collector>": {"added": [...], "removed": [...], "changed": {key: {from,to,delta}}}
      plus, if a collector appears in only one side:
      "added": ["<collector>", ...]   # present in latest, absent in past
      "removed": ["<collector>", ...]  # present in past, absent in latest
    """
    past_c = past.get("collectors", {})
    latest_c = latest.get("collectors", {})
    result: dict[str, Any] = {}

    only_past = set(past_c) - set(latest_c)
    only_latest = set(latest_c) - set(past_c)
    if only_past:
        result["removed"] = sorted(only_past)
    if only_latest:
        result["added"] = sorted(only_latest)

    for name in set(past_c) & set(latest_c):
        d = _diff_collector(past_c[name], latest_c[name])
        if d:
            result[name] = d
    return result


def _diff_collector(past: dict, latest: dict) -> dict[str, Any] | None:
    """Diff one collector's payload. Returns None if no changes."""
    out: dict[str, Any] = {}
    all_keys = set(past) | set(latest)
    for key in sorted(all_keys):
        pv = past.get(key)
        lv = latest.get(key)
        if pv == lv:
            continue
        if isinstance(pv, list) or isinstance(lv, list):
            added, removed = _setdiff(pv or [], lv or [])
            part: dict[str, Any] = {}
            if added:
                part["added"] = added
            if removed:
                part["removed"] = removed
            if part:
                out[key] = part
        elif isinstance(pv, (int, float)) and isinstance(lv, (int, float)) \
                and not isinstance(pv, bool) and not isinstance(lv, bool):
            out[key] = {"from": pv, "to": lv, "delta": round(lv - pv, 4)}
        else:
            # scalar non-numeric changed (e.g. manager string) — record the swap
            out[key] = {"from": pv, "to": lv}
    return out or None


def _setdiff(past_list: list, latest_list: list) -> tuple[list, list]:
    """Set difference of two lists, preserving JSON-serializable items (incl. dicts)."""
    past_set = {_key(x): x for x in past_list}
    latest_set = {_key(x): x for x in latest_list}
    added = [latest_set[k] for k in latest_set if k not in past_set]
    removed = [past_set[k] for k in past_set if k not in latest_set]
    return added, removed


def _key(item: Any) -> str:
    """Stable hashable key for a list member (dicts -> json, scalars -> str(item))."""
    if isinstance(item, dict):
        return json.dumps(item, sort_keys=True, default=str)
    return repr(item)


# ---- plain-English summary -------------------------------------------------


def summarize(diff_result: dict, label_a: str | None, label_b: str | None) -> str:
    """Render a structured diff as a plain-English paragraph."""
    a = label_a or "the earlier snapshot"
    b = label_b or "the later snapshot"
    if not _has_any_change(diff_result):
        return f"No changes between '{a}' and '{b}'."

    parts: list[str] = [f"Compared '{a}' → '{b}'. Changes:"]
    for collector, d in diff_result.items():
        if collector in ("added", "removed"):
            continue
        line = _summarize_collector(collector, d)
        if line:
            parts.append(line)

    if diff_result.get("added"):
        parts.append(f"new collector(s) appeared: {', '.join(diff_result['added'])}.")
    if diff_result.get("removed"):
        parts.append(f"collector(s) disappeared: {', '.join(diff_result['removed'])}.")

    return " ".join(parts)


def _has_any_change(diff_result: dict) -> bool:
    for k, v in diff_result.items():
        if k in ("added", "removed"):
            if v:
                return True
            continue
        if v:
            return True
    return False


def _summarize_collector(name: str, d: dict) -> str:
    """One sentence-ish per collector."""
    fragments: list[str] = []
    for key, change in d.items():
        if isinstance(change, dict) and ("added" in change or "removed" in change):
            added = change.get("added", [])
            removed = change.get("removed", [])
            human = _human_key(name, key)
            if added:
                names = [_short(x) for x in added[:5]]
                more = f" (+{len(added) - 5} more)" if len(added) > 5 else ""
                fragments.append(f"{len(added)} {human} added ({', '.join(names)}{more})")
            if removed:
                names = [_short(x) for x in removed[:5]]
                more = f" (+{len(removed) - 5} more)" if len(removed) > 5 else ""
                fragments.append(f"{len(removed)} {human} removed ({', '.join(names)}{more})")
        elif isinstance(change, dict) and "from" in change and "to" in change and "delta" in change:
            fragments.append(
                f"{_human_key(name, key)} changed {change['from']} → {change['to']} "
                f"(delta {change['delta']:+g})"
            )
        elif isinstance(change, dict) and "from" in change:
            fragments.append(f"{name}.{key} changed {change['from']} → {change['to']}")
    if not fragments:
        return ""
    return f"{name}: " + "; ".join(fragments) + "."


def _human_key(collector: str, key: str) -> str:
    """Map a collector+key to a human noun for the summary."""
    table = {
        ("ports", "listeners"): "port(s)",
        ("packages", "installed"): "package(s)",
        ("users", "users"): "user(s)",
        ("services", "labels"): "service(s)",
        ("services", "units"): "service(s)",
        ("cron", "entries"): "cron entr(y/ies)",
        ("cron", "agents"): "launchd agent(s)",
        ("cron", "cron_d"): "cron.d file(s)",
    }
    return table.get((collector, key), key)


def _short(item: Any) -> str:
    """Short human label for a list member in the summary."""
    if isinstance(item, dict):
        # ports: {proto, port, proc} -> "8080/tcp"
        if "port" in item:
            return f"{item['port']}/{item.get('proto', 'tcp')}"
        return ", ".join(f"{k}={v}" for k, v in list(item.items())[:2])
    return str(item)
