"""Print Claude subscription limits as JSON, using Hermes' own read-only fetcher.

Run with the Hermes tools python plus a Hermes venv on PYTHONPATH (the daemon does this).
Prints only percentages, labels and reset times. Never prints credentials.
"""
import json, os, sys

sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR") or os.path.expanduser("~/.hermes/hermes-agent"))

out = {"ok": False, "error": None, "plan": None, "windows": []}
try:
    from agent.account_usage import fetch_account_usage
    snap = fetch_account_usage("anthropic", read_only=True)
    if snap is None:
        out["error"] = "no Claude login visible to Hermes"
    elif snap.unavailable_reason:
        out["error"] = snap.unavailable_reason
    else:
        out["ok"] = bool(snap.windows)
        out["plan"] = snap.plan
        for w in snap.windows:
            used = w.used_percent
            out["windows"].append({
                "label": w.label,
                "used_pct": used,
                "remaining_pct": None if used is None else round(max(0.0, 100.0 - float(used)), 1),
                "reset_at": w.reset_at.isoformat() if w.reset_at else None,
                "scope": w.scope,
            })
        if not out["windows"]:
            out["error"] = "no windows returned"
except Exception as e:  # report, never crash the daemon
    out["error"] = f"{type(e).__name__}: {str(e)[:120]}"

print(json.dumps(out))
