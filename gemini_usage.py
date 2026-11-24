"""Print Google Gemini API-key status as JSON.

Google does not expose a remaining-quota figure for API keys (limits are shown only in
AI Studio / Cloud Console), so this reports what is actually knowable:
  1. does the key work right now: a free models.list call (no inference, no quota spent);
     HTTP 429 means the key is rate-limited at this moment
  2. what Hermes itself used through Gemini routes in the last 24h (read-only from state.db)
The key is read in memory from ~/.hermes/.env and never printed.
"""
import json, os, re, sqlite3, time, urllib.error, urllib.request
from pathlib import Path

out = {"ok": False, "error": None, "plan": "API key", "windows": [], "credits": None, "notes": []}


def read_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    envfile = Path(os.environ.get("GEMINI_ENV_FILE") or Path.home() / ".hermes" / ".env")
    if not envfile.exists():
        return ""
    for line in envfile.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?GEMINI_API_KEY\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    return ""


try:
    key = read_key()
    if not key:
        out["error"] = "no GEMINI_API_KEY (environment or GEMINI_ENV_FILE)"
    else:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
            headers={"x-goog-api-key": key, "User-Agent": "quota-board/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                out["ok"] = r.status == 200
                out["notes"].append("Key works")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                out["ok"] = True
                out["notes"].append("Key works but Google is rate-limiting it right now (HTTP 429)")
            elif e.code in (400, 401, 403):
                out["error"] = f"Google rejected the key (HTTP {e.code})"
            else:
                out["error"] = f"Google returned HTTP {e.code}"
        del key, req

    if out["ok"]:
        try:
            con = sqlite3.connect("file:" + str(Path(os.environ.get("HERMES_STATE_DB") or Path.home() / ".hermes" / "state.db")) + "?mode=ro", uri=True, timeout=5)
            calls = inp = outp = 0
            since = time.time() - 86400
            for prov in ("gemini", "custom:gemini"):
                r = con.execute(
                    "SELECT COALESCE(SUM(api_call_count),0), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) "
                    "FROM sessions WHERE billing_provider=? AND started_at>=?", (prov, since)).fetchone()
                calls, inp, outp = calls + r[0], inp + r[1], outp + r[2]
            con.close()
            out["notes"].append(f"Hermes used it in the last 24h: {calls:,} calls · {inp:,} in / {outp:,} out tokens")
        except Exception:
            pass
        # Per-model used-vs-limit comes from AI Studio's Rate Limit page, scraped every
        # 5 min by gemini_studio.py into $QUOTA_CACHE_DIR/gemini-studio.json (optional).
        try:
            st = json.loads((Path(os.environ.get("QUOTA_CACHE_DIR") or Path.home() / ".cache" / "quota-board") / "gemini-studio.json").read_text())
            age = int(time.time() - st.get("fetched_at", 0))
            if not st.get("ok"):
                out["notes"].append("AI Studio per-model limits unavailable: " + str(st.get("error")))
            else:
                if st.get("tier"):
                    out["plan"] = st["tier"]
                avail = [m for m in st["models"] if m["available"]]
                blocked = len(st["models"]) - len(avail)
                names = {"rpm": "requests/min", "tpm": "tokens/min", "rpd": "requests/day"}
                for m in avail:
                    for k, label in names.items():
                        p = m[k]
                        if (p["used"] or 0) > 0 and p["limit"]:
                            left = max(0.0, 100.0 * (1 - p["used"] / p["limit"]))
                            out["windows"].append({"label": f"{m['model']} · {label}", "remaining_pct": left, "reset_at": None})
                if not out["windows"]:
                    out["notes"].append("No Gemini usage on this key in the last 24 h")
                out["table"] = sorted(
                    [{"model": m["model"], "category": m["category"],
                      "rpm": m["rpm"]["text"], "tpm": m["tpm"]["text"], "rpd": m["rpd"]["text"],
                      "used": sum((m[k]["used"] or 0) for k in names) > 0} for m in avail],
                    key=lambda r: (not r["used"], r["category"], r["model"]))
                out["table_note"] = f"{len(avail)} models usable on this tier · {blocked} have no free-tier quota"
                out["notes"].append(f"Peak use vs limit over the last 24 h, from AI Studio ({age // 60} min ago"
                                    + (f"; refresh failing: {st['stale_error']}" if st.get("stale_error") else "") + ")")
        except FileNotFoundError:
            out["notes"].append("AI Studio per-model limits not collected yet")
        except Exception as e:
            out["notes"].append(f"AI Studio cache unreadable: {type(e).__name__}")
except Exception as e:
    out["error"] = f"{type(e).__name__}: {str(e)[:100]}"

print(json.dumps(out))
