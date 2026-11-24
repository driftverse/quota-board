"""Print Nous Portal limits as JSON using Hermes' own portal-account fetcher.

Tries the stored token first (no refresh); only if that fails does it fall back to Hermes'
normal fresh fetch, which is what Hermes' /usage does. Prints only plan, percentages, reset
times, the top-up balance and a couple of note lines. Never prints a token.
Run with the Hermes tools python plus a Hermes venv site-packages on PYTHONPATH.
"""
import json, os, sys

sys.path.insert(0, os.environ.get("HERMES_AGENT_DIR") or os.path.expanduser("~/.hermes/hermes-agent"))

out = {"ok": False, "error": None, "plan": None, "windows": [], "credits": None, "notes": []}
try:
    import agent.account_usage_nous as n
    snap, last = None, None
    for stored_only in (True, False):
        try:
            info = n._fetch_portal_account(15.0, stored_token_only=stored_only)
            snap = n.build_nous_credits_snapshot(info, cta=False)
            if snap is not None and snap.windows:
                break
        except Exception as e:
            last = e
    if snap is None or not snap.windows:
        out["error"] = f"{type(last).__name__}: {str(last)[:100]}" if last else "no Nous windows returned"
    else:
        out["plan"] = snap.plan
        for w in snap.windows:
            used = w.used_percent
            out["windows"].append({
                "label": w.label, "used_pct": used,
                "remaining_pct": None if used is None else round(max(0.0, 100.0 - float(used)), 1),
                "reset_at": w.reset_at.isoformat() if w.reset_at else None, "scope": w.scope,
            })
        for d in snap.details:
            if d.lower().startswith("top-up credits"):
                out["credits"] = d.split(":", 1)[1].strip()
            else:
                out["notes"].append(d)
        out["ok"] = True
except Exception as e:
    out["error"] = f"{type(e).__name__}: {str(e)[:120]}"

print(json.dumps(out))
