"""Print Codex/ChatGPT subscription limits as JSON by asking the Codex app-server itself.

The Codex CLI owns its login (~/.codex/auth.json) and refreshes its own tokens, so this
script never reads or handles a token (a token-reading version goes stale: 401 after ~10 days).
It starts `codex app-server` over stdio, does the JSON-RPC handshake, calls
account/rateLimits/read, prints only plan, percentages, reset times and a credits line,
then stops the server. Needs ~/.codex writable (the CLI may refresh its own auth.json).
"""
import json, os, select, shutil, subprocess, time
from datetime import datetime, timezone

CODEX = os.environ.get("CODEX_BIN") or shutil.which("codex") or "/usr/lib/chatgpt/resources/codex"
out = {"ok": False, "error": None, "plan": None, "windows": [], "details": []}


def send(p, obj):
    p.stdin.write((json.dumps(obj) + "\n").encode())
    p.stdin.flush()


def read_until(p, want_id, deadline):
    buf = b""
    while time.time() < deadline:
        r, _, _ = select.select([p.stdout], [], [], 0.5)
        if not r:
            if p.poll() is not None:
                break
            continue
        chunk = os.read(p.stdout.fileno(), 65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == want_id:
                return msg
    return None


def label_for(mins):
    if mins == 300:
        return "Session (5h)"
    if mins == 10080:
        return "Weekly"
    return f"{mins} min" if mins else "Window"


p = None
try:
    p = subprocess.Popen([CODEX, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=dict(os.environ, HOME=os.path.expanduser("~")))
    deadline = time.time() + 40
    send(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"clientInfo": {"name": "quota-board", "version": "1.0"}}})
    if read_until(p, 1, deadline) is None:
        raise RuntimeError("no reply to initialize")
    send(p, {"jsonrpc": "2.0", "method": "initialized"})
    send(p, {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {}})
    resp = read_until(p, 2, deadline)
    if resp is None:
        raise RuntimeError("no reply to account/rateLimits/read")
    if "error" in resp:
        raise RuntimeError(str((resp["error"] or {}).get("message", "error"))[:140])
    snap = (resp.get("result") or {}).get("rateLimits") or {}
    out["plan"] = snap.get("planType")
    for key in ("primary", "secondary"):
        w = snap.get(key)
        if not w:
            continue
        used = float(w.get("usedPercent", 0))
        reset = w.get("resetsAt")
        out["windows"].append({
            "label": label_for(w.get("windowDurationMins")),
            "used_pct": used, "remaining_pct": round(max(0.0, 100.0 - used), 1),
            "reset_at": datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset else None,
            "scope": "account",
        })
    cr = snap.get("credits") or {}
    if cr.get("unlimited"):
        out["details"].append("Credits balance: unlimited")
    elif cr.get("hasCredits") and cr.get("balance") is not None:
        out["details"].append(f"Credits balance: {cr['balance']}")
    out["ok"] = bool(out["windows"])
    if not out["ok"]:
        out["error"] = "Codex returned no limit windows"
except Exception as e:
    out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
finally:
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()

print(json.dumps(out))
