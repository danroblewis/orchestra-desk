// The Desk's ledger: what happened, by day or week (local time) or all of it, filtered by kind and
// to the owner's own acts, each entry linked to where it happened. The view lives in the URL's
// hash (#period=week&at=2026-10-26&kind=merged,landed&mine=1), so a view can be linked.
(function () {
  const API = "/api/plugins/desk";
  const safe = (u) => (u && (/^https?:\/\//.test(u) || (u[0] === "/" && u[1] !== "/")) ? u : null);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const V = { period: "week", at: iso(new Date()), kind: [], mine: false };

  function readHash() {
    const h = new URLSearchParams(location.hash.slice(1));
    if (["day", "week", "all"].includes(h.get("period"))) V.period = h.get("period");
    if (/^\d{4}-\d{2}-\d{2}$/.test(h.get("at") || "")) V.at = h.get("at");
    V.kind = (h.get("kind") || "").split(",").filter(Boolean);
    V.mine = h.get("mine") === "1";
  }
  function writeHash() {
    const h = new URLSearchParams({ period: V.period, at: V.at });
    if (V.kind.length) h.set("kind", V.kind.join(","));
    if (V.mine) h.set("mine", "1");
    history.replaceState(null, "", "#" + h.toString());
  }
  function shift(n) {
    const d = new Date(V.at + "T12:00:00");
    d.setDate(d.getDate() + n * (V.period === "week" ? 7 : 1));
    V.at = iso(d); load();
  }

  function entry(e) {
    const t = new Date(e.at * 1000);
    const what = safe(e.link) ? `<a href="${esc(e.link)}" target="${e.link[0] === "/" ? "_self" : "_blank"}" rel="noopener">${esc(e.label || e.subject || e.type)}</a>`
      : esc(e.label || e.subject || e.type);
    const by = e.source ? `<span class="dk-by">by ${esc(e.source)}</span>` : "";
    return `<div class="dk-entry ${e.mine ? "dk-mine" : ""}" title="${esc(e.type)} · ${esc(e.id)}">
      <span class="dk-time">${esc(t.toTimeString().slice(0, 5))}</span><span class="dk-k">${esc(e.kind)}</span>
      <span class="dk-what">${what}${by}</span></div>`;
  }

  function draw(d) {
    document.querySelectorAll("#dk-period button").forEach((b) => b.classList.toggle("on", b.dataset.p === V.period));
    $("dk-name").textContent = d.name || "";
    $("dk-prev").disabled = $("dk-next").disabled = V.period === "all";
    const counts = d.counts || {};
    $("dk-kinds").innerHTML = (d.kinds || []).map((k) => `<button class="dk-kind ${V.kind.includes(k) ? "on" : ""}" data-k="${esc(k)}">${esc(k)}<b>${counts[k] || 0}</b></button>`).join("");
    document.querySelectorAll(".dk-kind").forEach((b) => (b.onclick = () => {
      const k = b.dataset.k;
      V.kind = V.kind.includes(k) ? V.kind.filter((x) => x !== k) : [...V.kind, k];
      load();
    }));
    const st = [];
    if (d.error) st.push(`<span class="dk-bad">[desk] is not usable: ${esc(d.error)}</span>`);
    else if (!d.configured) st.push(`This project has no <code>[desk]</code> section, so the ledger is not kept.`);
    if (d.read_error) st.push(`<span class="dk-bad">the bus could not be read just now: ${esc(d.read_error)}</span>`);
    if (V.mine && !(d.owner || []).length) st.push(`<span class="muted">No <code>[desk] owner</code> is set, so only the Desk's own entries are yours.</span>`);
    $("dk-status").innerHTML = st.join(" · ");
    if (!d.entries.length) { $("dk-ledger").innerHTML = `<div class="empty">Nothing in ${esc(d.name || "this period")}.</div>`; return; }
    let day = null, html = "";
    for (const e of d.entries) {
      const dd = new Date(e.at * 1000).toDateString();
      if (dd !== day) { html += `<div class="dk-day">${esc(dd)}</div>`; day = dd; }
      html += entry(e);
    }
    $("dk-ledger").innerHTML = html;
  }

  async function load() {
    writeHash();
    const q = new URLSearchParams({ period: V.period, at: V.at, kind: V.kind.join(","), mine: V.mine ? "true" : "false" });
    try {
      const r = await fetch(`${API}/ledger?${q}`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      $("conn").textContent = "live";
      draw(d);
    } catch (e) {
      $("conn").textContent = "disconnected";
    }
  }

  readHash();
  document.querySelectorAll("#dk-period button").forEach((b) => (b.onclick = () => { V.period = b.dataset.p; load(); }));
  $("dk-prev").onclick = () => shift(-1);
  $("dk-next").onclick = () => shift(1);
  $("dk-mine").checked = V.mine;
  $("dk-mine").onchange = () => { V.mine = $("dk-mine").checked; load(); };
  load(); setInterval(load, 15000);
})();
