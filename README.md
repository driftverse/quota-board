# quota-board

A tiny, read-only web page that shows **how much is left on each of your AI subscriptions** and when it comes back: Claude, Codex/ChatGPT, Antigravity, Nous Portal, and a Gemini API key with per-model limits.

One Python file serves one static page plus `/api/subs`. A background thread refreshes every 60 s. No database, no dependencies beyond the Python standard library (the optional Gemini scraper needs `websockets`).

It never spends inference and never prints or stores a credential. Each source is read through the vendor's own CLI or a read-only usage endpoint.

## Honest limits

- **Some sources are tied to other tools.** Claude and Nous are read through [Hermes Agent](https://hermes-agent.nousresearch.com/)'s own account-usage helpers (`claude_usage.py`, `nous_usage.py` import `agent.account_usage*`). Without Hermes installed, turn those two off. Codex needs the Codex CLI or the ChatGPT desktop app's bundled `codex`. Antigravity needs the `agy` CLI.
- **Gemini per-model limits are scraped, so they are fragile.** Google has no quota API for API keys. `gemini_studio.py` reads AI Studio's *Rate Limit* page through a Chrome you've already signed in (Chrome DevTools Protocol). It breaks if Google redesigns the page, and automated reading of a logged-in Google page may be against Google's terms. It is optional and off unless you set `AISTUDIO_PROJECT`. The figures are *peak use over the last 24 h vs the limit*, not a live countdown.
- **There is no login on the page.** It binds to `127.0.0.1` by default. If you expose it, put real authentication in front (a tunnel with access control, a reverse proxy with auth). Do not publish it openly: it reveals your plans and usage.
- Tested on one Linux machine only. No automated tests yet.

## Run it

```bash
git clone <this repo> ~/quota-board && cd ~/quota-board
QUOTA_TZ=America/New_York python3 daemon.py        # http://127.0.0.1:9181
```

Pick which cards to show (default is all five; cards that can't connect say why):

```bash
QUOTA_PROVIDERS=codex,antigravity python3 daemon.py
```

## Settings (environment variables)

| Variable | Meaning | Default |
|---|---|---|
| `USAGE_DAEMON_HOST` / `USAGE_DAEMON_PORT` | Where the page listens | `127.0.0.1` / `9181` |
| `QUOTA_TZ` | Timezone for reset times | `UTC` |
| `QUOTA_PROVIDERS` | Comma list of `claude,antigravity,codex,nous,gemini` | all |
| `HERMES_HOME` | Hermes data dir (Claude/Nous/Gemini-usage helpers) | `~/.hermes` |
| `HERMES_AGENT_DIR` | Hermes agent source dir | `~/.hermes/hermes-agent` |
| `QUOTA_PYTHON` | Python that can import Hermes (needs `httpx`) | the daemon's own |
| `QUOTA_PYTHONPATH` | site-packages for that Python | auto-found in `HERMES_HOME/installs` |
| `AGY_BIN` | Antigravity CLI | `agy` on `PATH` |
| `CODEX_BIN` | Codex CLI | `codex` on `PATH`, then the ChatGPT app's copy |
| `GEMINI_API_KEY` or `GEMINI_ENV_FILE` | Key for the free `models.list` check | env var, then `~/.hermes/.env` |
| `AISTUDIO_PROJECT` | AI Studio project id (turns on the per-model scraper) | unset (off) |
| `AISTUDIO_PROJECT_NAME` | Label for that project | project id |
| `CDP_URL` | Signed-in Chrome with `--remote-debugging-port` | `http://127.0.0.1:9222` |
| `QUOTA_CACHE_DIR` | Where the scraper cache is written | `~/.cache/quota-board` |

## Run it as a service (systemd, user)

```bash
mkdir -p ~/.config/systemd/user && cp systemd/* ~/.config/systemd/user/
# edit the paths and Environment= lines first
systemctl --user daemon-reload
systemctl --user enable --now quota-board.service
# optional Gemini scraper, every 5 min:
systemctl --user enable --now quota-board-gemini-studio.timer
```

The unit is sandboxed (`ProtectSystem=strict`) and only gets write access to the folders the vendor CLIs need to refresh their own state.

## How each card is read

| Card | Source |
|---|---|
| Claude | Hermes' read-only Anthropic usage fetch |
| Codex / ChatGPT | `codex app-server` JSON-RPC `account/rateLimits/read` (the CLI keeps its own login fresh; this code never touches a token) |
| Antigravity | `agy -p /usage`, `agy -p /credits` |
| Nous Portal | Hermes' portal-account fetch |
| Gemini key | free `models.list` call (works / rate-limited) + optional AI Studio table |

## Files

`daemon.py` server · `subs.py` collector · `*_usage.py` one helper per source · `gemini_studio.py` optional scraper · `index.html`, `app.css`, `app.js` the page · `systemd/` unit templates.

## License

MIT, see `LICENSE`.
