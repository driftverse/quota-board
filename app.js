/* quota board page: polls /api/subs (a cache read) and re-renders. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let TZ = "UTC";   // replaced by the server's QUOTA_TZ once data arrives
  let data = null, lastOk = 0;

  function resetText(iso) {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (!isFinite(t)) return "";
    const ms = t - Date.now();
    if (ms <= 0) return "resetting now";
    const m = Math.round(ms / 60000), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
    const left = d ? d + "d " + h + "h" : h ? h + "h " + mm + "m" : mm + "m";
    const when = new Date(t).toLocaleString("en-US", { timeZone: TZ, weekday: "short", hour: "numeric", minute: "2-digit" });
    return "resets in " + left + " · " + when;
  }

  function winHtml(w) {
    const p = w.remaining_pct;
    const cls = p == null ? "na" : p <= 0 ? "out" : p < 20 ? "low" : "ok";
    const big = p == null ? (w.state || "n/a") : Math.round(p) + "%";
    const bar = p == null ? "" : '<div class="bar"><i class="' + cls + '" style="width:' + Math.max(0, Math.min(100, p)) + '%"></i></div>';
    return '<div class="win"><div class="win-row"><span class="win-label">' + esc(w.label) + ' left</span>' +
      '<span class="pct ' + cls + '">' + esc(big) + "</span></div>" + bar +
      '<div class="reset">' + esc(resetText(w.reset_at)) + "</div></div>";
  }

  function cardHtml(x) {
    const body = x.ok
      ? (x.windows || []).map(winHtml).join("")
      : '<div class="err"><b>not connected</b><br>' + esc(x.error || "no data") + "</div>";
    const notes = x.ok && (x.notes || []).length
      ? '<ul class="notes">' + x.notes.map((n) => "<li>" + esc(n) + "</li>").join("") + "</ul>" : "";
    const cred = x.credits != null
      ? '<div class="credits"><span>credits left</span><strong>' + esc(x.credits) + "</strong></div>" : "";
    const tbl = x.ok && (x.table || []).length
      ? '<details class="models"><summary>' + esc(x.table_note || "models") + '</summary><div class="tbl-wrap"><table><thead><tr>' +
        "<th>model</th><th>req/min</th><th>tokens/min</th><th>req/day</th></tr></thead><tbody>" +
        x.table.map((r) => '<tr class="' + (r.used ? "used" : "") + '"><td>' + esc(r.model) + "</td><td>" + esc(r.rpm) +
          "</td><td>" + esc(r.tpm) + "</td><td>" + esc(r.rpd) + "</td></tr>").join("") + "</tbody></table></div></details>" : "";
    return '<article class="card' + (x.ok ? "" : " off") + '"><div class="card-head"><span class="card-name">' +
      esc(x.name) + '</span><span class="card-plan">' + esc(x.plan || "") + "</span></div>" + body + notes + tbl + cred + "</article>";
  }

  function render() {
    const grid = $("#grid");
    const subs = (data && data.subscriptions) || [];
    grid.innerHTML = subs.length ? subs.map(cardHtml).join("") : '<div class="empty">collecting the first reading…</div>';
    const ago = lastOk ? Math.round((Date.now() - lastOk) / 1000) : null;
    const stale = ago == null || ago > 150;
    $("#dot").className = "dot " + (stale ? "stale" : "live");
    $("#fresh").textContent = data && data.fetched_at
      ? "checked " + new Date(data.fetched_at).toLocaleTimeString("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit", second: "2-digit" }) + (stale ? " · stale" : "")
      : "loading…";
  }

  async function load() {
    try {
      const r = await fetch("/api/subs", { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      data = await r.json();
      if (data.tz) TZ = data.tz;
      lastOk = Date.now();
    } catch (e) { /* keep the last good data; the dot turns red when it goes stale */ }
    render();
  }

  $("#refresh").addEventListener("click", load);
  load();
  setInterval(load, 15000);
  setInterval(render, 30000);   // keeps "resets in" countdowns moving between loads
})();
