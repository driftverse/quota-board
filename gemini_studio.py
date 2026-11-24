"""Scrape AI Studio's Rate Limit page (all Gemini models, used vs limit) into a cache file.

OPTIONAL and fragile: Google has no quota API for keys, so this reads the web page in a
Chrome that is already signed in to the Google account that owns the API key's project
(Chrome started with --remote-debugging-port, see CDP_URL). Read-only: opens a throwaway
tab, never types credentials, closes the tab afterwards. Breaks if Google redesigns the page.

Required: AISTUDIO_PROJECT (the project id, e.g. gen-lang-client-0123456789).
Optional: CDP_URL (default http://127.0.0.1:9222), QUOTA_CACHE_DIR, AISTUDIO_PROJECT_NAME.
Writes $QUOTA_CACHE_DIR/gemini-studio.json atomically. Needs `pip install websockets`.
"""
import asyncio, json, os, re, sys, time, urllib.request
from pathlib import Path
import websockets

PROJECT = os.environ.get("AISTUDIO_PROJECT", "")
RANGE = "last-1-day"
URL = f"https://aistudio.google.com/rate-limit?project={PROJECT}&timeRange={RANGE}"
CDP = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
OUT = Path(os.environ.get("QUOTA_CACHE_DIR") or Path.home() / ".cache" / "quota-board") / "gemini-studio.json"

EXTRACT = r"""(() => {
  const clean = s => (s || '').trim().replace(/\s+/g, ' ');
  const rows = [...document.querySelectorAll('table tr, [role=row]')].map(r =>
    [...r.querySelectorAll('td,th,[role=cell],[role=gridcell],[role=columnheader]')].map(c => clean(c.innerText))
  ).filter(a => a.length >= 6);
  const acct = (document.body.innerText.match(/[\w.+-]+@[\w-]+\.[\w.]+/) || [''])[0];
  const tier = (document.body.innerText.match(/\n(Free tier|Tier \d|Paid tier[^\n]*)\n/) || ['', ''])[1];
  return JSON.stringify({rows, acct, tier, url: location.href});
})()"""

CLICK_MORE = r"""(() => { const b = [...document.querySelectorAll('button,[role=button]')]
  .find(x => /See more/i.test(x.innerText || '')); if (b) { b.click(); return true } return false })()"""


def num(s):
    """'2.69K' -> 2690, '0' -> 0, 'Unlimited' -> None (no cap), '-' -> None."""
    s = s.strip()
    m = re.fullmatch(r"([\d.,]+)\s*([KMB]?)", s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return int(round(v * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]))


def pair(s):
    if "/" not in s:
        return {"used": None, "limit": None, "unlimited": False, "text": s}
    a, b = [x.strip() for x in s.split("/", 1)]
    return {"used": num(a), "limit": num(b), "unlimited": b.lower() == "unlimited", "text": s}


def http_json(path, method="GET"):
    req = urllib.request.Request(CDP + path, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "null")


async def scrape():
    tab = http_json("/json/new?about:blank", "PUT")
    try:
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=30 * 1024 * 1024) as ws:
            n = 0

            async def call(method, params=None):
                nonlocal n
                n += 1
                my = n
                await ws.send(json.dumps({"id": my, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if msg.get("id") == my:
                        return msg.get("result") or {}

            async def ev(expr):
                r = await call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "userGesture": True})
                return (r.get("result") or {}).get("value")

            await call("Page.enable")
            await call("Page.navigate", {"url": URL})
            deadline = time.time() + 60
            data = None
            clicked = False
            while time.time() < deadline:
                await asyncio.sleep(2.5)
                url = await ev("location.href") or ""
                if "accounts.google.com" in url:
                    return {"ok": False, "error": "the browser is signed out of Google (AI Studio redirected to sign-in)"}
                try:
                    if not clicked and await ev("document.body.innerText.includes('Rate limits by model')"):
                        clicked = bool(await ev(CLICK_MORE))
                        await asyncio.sleep(2)
                    raw = await ev(EXTRACT)
                    data = json.loads(raw) if raw else None
                except Exception:
                    data = None
                if data and len(data["rows"]) > 5:
                    break
            if not data or len(data["rows"]) <= 5:
                return {"ok": False, "error": "AI Studio rate-limit table did not load"}
            return {"ok": True, "data": data}
    finally:
        try:
            http_json("/json/close/" + tab["id"])
        except Exception:
            pass


def build(data):
    models, seen = [], set()
    for r in data["rows"]:
        if r[1] == "Model":
            continue
        name, cat = r[1], r[2]
        key = (name, cat)
        if key in seen:
            continue
        seen.add(key)
        rpm, tpm, rpd = pair(r[3]), pair(r[4]), pair(r[5])
        # a limit of 0 means this model is not available on the project's tier
        avail = any((p["limit"] or 0) > 0 or p["unlimited"] for p in (rpm, tpm, rpd))
        models.append({"model": name, "category": cat, "rpm": rpm, "tpm": tpm, "rpd": rpd, "available": avail})
    return {"ok": True, "error": None, "fetched_at": int(time.time()), "range": RANGE,
            "account": data.get("acct"), "tier": data.get("tier") or None, "project": os.environ.get("AISTUDIO_PROJECT_NAME", PROJECT),
            "models": models}


def main():
    if not PROJECT:
        print(json.dumps({"ok": False, "error": "set AISTUDIO_PROJECT"}))
        return 2
    try:
        res = asyncio.run(scrape())
        out = build(res["data"]) if res["ok"] else {"ok": False, "error": res["error"], "fetched_at": int(time.time())}
    except Exception as e:
        out = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}", "fetched_at": int(time.time())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # keep the last good data if this run failed
    if not out["ok"] and OUT.exists():
        try:
            old = json.loads(OUT.read_text())
            if old.get("ok"):
                old["stale_error"], old["stale_since"] = out["error"], out["fetched_at"]
                out = old
        except Exception:
            pass
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, OUT)
    print(json.dumps({"ok": out.get("ok"), "error": out.get("error") or out.get("stale_error"),
                      "models": len(out.get("models", [])), "tier": out.get("tier")}))


if __name__ == "__main__":
    sys.exit(main())
