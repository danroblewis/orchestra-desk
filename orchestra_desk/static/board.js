// The Desk's board: every standing condition, false ones first (ranked by the server, board.py),
// each with its evidence, a script's reason, and links to where to act and to the readings.
// Reads /api/plugins/desk/board every 10 s.
(function () {
  const API = "/api/plugins/desk";
  const safe = (u) => (u && (/^https?:\/\//.test(u) || (u[0] === "/" && u[1] !== "/")) ? u : null);
  const link = (u, text) => (safe(u) ? `<a href="${esc(u)}" target="${u[0] === "/" ? "_self" : "_blank"}" rel="noopener">${esc(text)}</a>` : "");
  const when = (t) => (t ? new Date(t * 1000).toLocaleString() : "never");
  const target = () => decodeURIComponent((location.hash.match(/^#condition=(.+)$/) || [])[1] || "");

  function card(c, now) {
    const sev = `<span class="dk-badge dk-sev-${esc(c.severity)}">${esc(c.severity)}</span>`;
    const state = c.state === "false" ? `false for ${c.false_for != null ? ago(c.false_for) : "?"}`
      : c.state === "holds" ? `holds${c.since ? ` for ${ago(now - c.since)}` : ""}` : "unknown";
    const how = c.check === "script" ? `script <code>${esc((c.command || []).join(" "))}</code>`
      : `holds when ${esc(c.check === "expr" ? "the expression" : "the value")} ${esc(c.holds_when || "")}`;
    return `<div class="dk-cond dk-${esc(c.state)} ${target() === c.name ? "dk-target" : ""}" id="cond-${esc(c.name)}">
      <div class="dk-top"><span class="dk-statement">${esc(c.statement)}</span>
        <span class="dk-badge dk-s-${esc(c.state)}">${esc(state)}</span>${sev}</div>
      <div class="dk-meta"><span class="dk-name">${esc(c.name)}</span><span>${how}</span>
        ${c.value != null ? `<span>value <b class="num">${esc(+c.value.toFixed(4))}</b></span>` : ""}
        <span class="muted">checked ${c.checked_at ? esc(ago(Math.max(now - c.checked_at, 0))) + " ago" : "not yet"}</span>
        ${link(c.link, "act on it ↗")} ${link(c.evidence_link, "readings")}</div>
      ${c.reason ? `<div class="dk-reason">${esc(c.reason)}</div>` : ""}
      <div class="dk-evidence">${esc(c.evidence)}</div></div>`;
  }

  async function refresh() {
    try {
      const d = await (await fetch(API + "/board")).json();
      $("conn").textContent = "live";
      if (d.error) {
        $("dk-status").innerHTML = `<span class="dk-bad">[desk] is not usable: ${esc(d.error)}</span>`;
      } else if (!d.configured) {
        $("dk-status").innerHTML = `This project has no <code>[desk]</code> section. Conditions are configured in <code>[desk.conditions]</code> (ask the Supervisor).`;
      } else {
        const c = d.counts || {};
        $("dk-status").innerHTML = `<b>${c.false || 0}</b> false · <b>${c.unknown || 0}</b> unknown · <b>${c.holds || 0}</b> hold
          <span class="muted"> · last checked ${esc(when(d.checked_at))}, every ${esc(d.every)}s</span>`;
      }
      $("dk-board").innerHTML = d.conditions.length ? d.conditions.map((c) => card(c, d.now)).join("")
        : `<div class="empty">No conditions configured.</div>`;
      const t = target() && document.getElementById("cond-" + target());
      if (t && !refresh.scrolled) { t.scrollIntoView({ block: "center" }); refresh.scrolled = true; }
    } catch (e) {
      $("conn").textContent = "disconnected";
    }
  }
  window.addEventListener("hashchange", () => { refresh.scrolled = false; refresh(); });
  refresh(); setInterval(refresh, 10000);
})();
