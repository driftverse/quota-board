"""Subscription quota collector for the usage dashboard.

Sources (all read-only, none spend inference):
  - Claude   : Hermes' account-usage fetcher (Anthropic OAuth usage API), via claude_usage.py
  - Antigravity (Gemini, shared Claude+GPT, credits): `agy -p /usage` and `agy -p /credits`
  - Codex    : asks the Codex app-server itself (it owns its login), via codex_usage.py
  - Nous Portal, Gemini API key: via nous_usage.py and gemini_usage.py

A background thread refreshes every REFRESH_S and caches the result; /api/usage only reads the cache.
"""
import glob, json, os, shutil, subprocess, sys, tempfile, threading, time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REFRESH_S = 60
# Everything machine-specific comes from the environment (see README).
TOOLS_PY = Path(os.environ.get("QUOTA_PYTHON") or sys.executable)   # python that can import the Hermes agent
AGY = Path(os.environ.get("AGY_BIN") or shutil.which("agy") or HOME / ".local/bin/agy")
TZ = os.environ.get("QUOTA_TZ", "UTC")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", HOME / ".hermes"))
PROVIDERS = [p.strip() for p in os.environ.get("QUOTA_PROVIDERS", "claude,antigravity,codex,nous,gemini").split(",") if p.strip()]
HELPER = Path(__file__).resolve().parent / "claude_usage.py"
CODEX_HELPER = Path(__file__).resolve().parent / "codex_usage.py"
NOUS_HELPER = Path(__file__).resolve().parent / "nous_usage.py"
GEMINI_HELPER = Path(__file__).resolve().parent / "gemini_usage.py"
CWD = Path(os.environ.get("QUOTA_WORKDIR") or Path(tempfile.gettempdir()) / "quota-board")

_lock = threading.Lock()
_cache = {"fetched_at": None, "subscriptions": []}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _site_packages():
    # QUOTA_PYTHONPATH wins; otherwise any Hermes venv that has httpx works for the read-only fetcher
    if os.environ.get("QUOTA_PYTHONPATH"):
        return os.environ["QUOTA_PYTHONPATH"]
    for sp in sorted(glob.glob(str(HERMES_HOME / "installs/*/environments/*/venv/lib/python3.*/site-packages"))):
        if os.path.isdir(os.path.join(sp, "httpx")):
            return sp
    return None


def _claude():
    sub = {"id": "claude", "name": "Claude", "source": "Anthropic usage API", "ok": False,
           "error": None, "plan": None, "windows": [], "credits": None, "fetched_at": _now()}
    sp = _site_packages()
    if not sp or not TOOLS_PY.exists():
        sub["error"] = "Hermes runtime not found"
        return sub
    try:
        env = dict(os.environ, HOME=str(HOME), PYTHONPATH=sp)
        r = subprocess.run([str(TOOLS_PY), str(HELPER)], capture_output=True, text=True, timeout=45, env=env)
        data = json.loads(r.stdout.strip().splitlines()[-1])
        sub["ok"], sub["error"], sub["plan"] = data["ok"], data["error"], data["plan"]
        sub["windows"] = [{"label": w["label"], "remaining_pct": w["remaining_pct"],
                           "reset_at": w["reset_at"], "state": "ok"} for w in data["windows"]]
    except Exception as e:
        sub["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return sub


def _agy(cmd):
    CWD.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(HOME), PATH=f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin")
    r = subprocess.run([str(AGY), "-p", cmd], capture_output=True, text=True, timeout=50, env=env, cwd=str(CWD))
    return r.stdout


def _antigravity():
    groups = {}
    err = None
    try:
        for line in _agy("/usage").splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            group, label, value = parts[0].strip(), parts[1].strip(), parts[2].strip()
            reset = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
            label = label.replace(" Limit Remaining", "")
            if value.endswith("%"):
                win = {"label": label, "remaining_pct": float(value.rstrip("%")), "reset_at": reset, "state": "ok"}
            else:  # e.g. "disabled" when the weekly allowance is exhausted
                win = {"label": label, "remaining_pct": None, "reset_at": reset, "state": value or "unknown"}
            groups.setdefault(group, []).append(win)
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:100]}"

    credits = None
    try:
        for line in _agy("/credits").splitlines():
            if line.lower().startswith("remaining credits"):
                credits = line.split("\t")[1].strip()
    except Exception:
        pass

    names = {"Gemini Models": ("antigravity-gemini", "Antigravity · Gemini"),
             "Claude and GPT models": ("antigravity-claude-gpt", "Antigravity · Claude + GPT")}
    subs = []
    for group, wins in groups.items():
        sid, name = names.get(group, ("antigravity-" + group.lower().replace(" ", "-"), "Antigravity · " + group))
        subs.append({"id": sid, "name": name, "source": "agy /usage", "ok": True, "error": None,
                     "plan": None, "windows": wins, "credits": None, "fetched_at": _now()})
    if not subs:
        subs.append({"id": "antigravity", "name": "Antigravity", "source": "agy /usage", "ok": False,
                     "error": err or "no usage lines returned", "plan": None, "windows": [],
                     "credits": None, "fetched_at": _now()})
    if credits is not None:
        subs[-1]["credits"] = credits   # credits are account-wide; shown on the last Antigravity card
    return subs


def _codex():
    sub = {"id": "codex", "name": "Codex / ChatGPT", "source": "Codex app-server", "ok": False,
           "error": None, "plan": None, "windows": [], "credits": None, "fetched_at": _now()}
    sp = _site_packages()
    if not sp or not TOOLS_PY.exists():
        sub["error"] = "Hermes runtime not found"
        return sub
    try:
        env = dict(os.environ, HOME=str(HOME), PYTHONPATH=sp)
        r = subprocess.run([str(TOOLS_PY), str(CODEX_HELPER)], capture_output=True, text=True, timeout=45, env=env)
        data = json.loads(r.stdout.strip().splitlines()[-1])
        sub["ok"], sub["error"], sub["plan"] = data["ok"], data["error"], data["plan"]
        sub["windows"] = [{"label": w["label"], "remaining_pct": w["remaining_pct"],
                           "reset_at": w["reset_at"], "state": "ok"} for w in data["windows"]]
        for d in data.get("details") or []:
            if d.lower().startswith("credits balance"):
                sub["credits"] = d.split(":", 1)[1].strip()
    except Exception as e:
        sub["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return sub


def _helper_card(sid, name, source, script, hermes_runtime):
    """Run a helper that prints one JSON object and turn it into a card."""
    sub = {"id": sid, "name": name, "source": source, "ok": False, "error": None, "plan": None,
           "windows": [], "credits": None, "notes": [], "fetched_at": _now()}
    try:
        env = dict(os.environ, HOME=str(HOME))
        if hermes_runtime:
            sp = _site_packages()
            if not sp or not TOOLS_PY.exists():
                sub["error"] = "Hermes runtime not found"
                return sub
            env["PYTHONPATH"] = sp
            cmd = [str(TOOLS_PY), str(script)]
        else:
            cmd = [sys.executable, str(script)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=50, env=env)
        data = json.loads(r.stdout.strip().splitlines()[-1])
        sub["ok"], sub["error"], sub["plan"] = data["ok"], data["error"], data.get("plan")
        sub["credits"], sub["notes"] = data.get("credits"), data.get("notes") or []
        sub["windows"] = [{"label": w["label"], "remaining_pct": w["remaining_pct"],
                           "reset_at": w["reset_at"], "state": "ok"} for w in data.get("windows") or []]
        if data.get("table"):
            sub["table"], sub["table_note"] = data["table"], data.get("table_note")
    except Exception as e:
        sub["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return sub


def _nous():
    return _helper_card("nous", "Nous Portal", "Hermes portal account", NOUS_HELPER, True)


def _gemini():
    return _helper_card("gemini-api", "Google Gemini API key", "AI Studio rate limits", GEMINI_HELPER, False)


def refresh():
    subs = []
    if "claude" in PROVIDERS:
        subs.append(_claude())
    if "antigravity" in PROVIDERS:
        subs += _antigravity()
    for name, fn in (("codex", _codex), ("nous", _nous), ("gemini", _gemini)):
        if name in PROVIDERS:
            subs.append(fn())
    with _lock:
        _cache["fetched_at"] = _now()
        _cache["subscriptions"] = subs


def get():
    with _lock:
        return {"fetched_at": _cache["fetched_at"], "refresh_s": REFRESH_S, "tz": TZ,
                "subscriptions": list(_cache["subscriptions"])}


def _loop():
    while True:
        try:
            refresh()
        except Exception:
            pass
        time.sleep(REFRESH_S)


def start():
    threading.Thread(target=_loop, name="subs-refresh", daemon=True).start()
