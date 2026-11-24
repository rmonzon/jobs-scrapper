// data.js (written by every run) sets window.__JT_DATA. It's a plain script
// rather than fetched JSON so the page also works when opened via file://.
const DATA = window.__JT_DATA || {
  missing: true, companies: [], jobs: [], filters: {}, prefs: {},
  new_count: 0, total_jobs: 0, remote_count: 0, update_ok: false,
  update_errors: ["dashboard/data.js not found: run python3 run.py"],
};
const $ = (id) => document.getElementById(id);
const TOKEN = DATA.logo_token;
const COLORS = ["#6f9bff","#8b6fff","#ff6f91","#ffa14a","#34d399","#22b8cf","#e879f9"];
const esc = (s) => (s||"").replace(/[&<>"]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));

// Header / stats
// generated_at is an ISO-8601 UTC instant; format it in the viewer's own
// timezone. Fall back to the raw value if it's ever not a parseable date.
function fmtUpdated(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}
$("upd").textContent = "Updated " + fmtUpdated(DATA.generated_at);

// Show whether the latest update completed cleanly.
(function () {
  const s = $("updStatus");
  if (DATA.update_ok) {
    s.textContent = "✓";              // ✓
    s.className = "upd-status ok";
    s.title = "Last update completed successfully";
  } else {
    s.textContent = "!";
    s.className = "upd-status warn";
    const errs = DATA.update_errors || [];
    s.title = "Last update had problems:\n" + (errs.length ? errs.join("\n") : "see logs");
  }
  s.hidden = false;
})();
$("stNew").textContent = DATA.new_count;
$("stTotal").textContent = DATA.total_jobs;
$("stCos").textContent = DATA.companies.length;
$("stRemote").textContent = DATA.remote_count;

// Banner
const banner = $("banner");
if (DATA.missing) {
  banner.classList.add("none");
  $("bannerTxt").textContent = "No dashboard data yet: run python3 run.py";
} else if (DATA.new_count > 0) {
  banner.classList.add("has");
  $("bannerTxt").textContent = DATA.new_count + (DATA.new_count === 1 ? " new role" : " new roles") + " discovered in today's run";
} else {
  banner.classList.add("none");
  $("bannerTxt").textContent = "You're all caught up — no new roles since the last run";
}

// Company filter
const sel = $("company");
sel.innerHTML = `<option value="">All Companies</option>` +
  DATA.companies.map(c => `<option value="${esc(c.company)}">${esc(c.company)} (${c.count})</option>`).join("");

function colorFor(name) {
  let h = 0; for (const ch of name) h = (h*31 + ch.charCodeAt(0)) >>> 0;
  return COLORS[h % COLORS.length];
}
function iniHtml(company) {
  const ini = esc(company.slice(0,2).toUpperCase());
  return `<span class="ini" style="background:${colorFor(company)}">${ini}</span>`;
}
function logoFail(img) { img.parentNode.innerHTML = iniHtml(img.getAttribute("data-co") || "?"); }
function logoHtml(company, domain) {
  if (TOKEN && domain) {
    const src = `https://img.logo.dev/${encodeURIComponent(domain)}?token=${encodeURIComponent(TOKEN)}&size=72&format=png&retina=true`;
    return `<span class="logo"><img src="${src}" alt="${esc(company)}" data-co="${esc(company)}" loading="lazy" onerror="logoFail(this)"></span>`;
  }
  return `<span class="logo">${iniHtml(company)}</span>`;
}

// ---- Persistent per-user state (survives every dashboard rebuild) -----------
// Followed/dismissed roles are saved server-side (data/preferences.json) when a
// live server (serve.py) is actually answering, so they sync across
// browsers/machines. On a static host (GitHub Pages) or over file:// there's no
// server, so we fall back to per-browser localStorage. We feature-detect the
// API rather than trusting the protocol: GitHub Pages is https:// but has no
// backend. Tracked roles are stored as full snapshots so a followed job can
// still be shown after it disappears from the live feed ("no longer available").
let serverPrefs = false;   // set true only once /api/prefs answers
const LS_TRACK = "jt_tracked_v1";   // { [id]: jobSnapshot }
const LS_HIDE  = "jt_hidden_v1";    // [ id, ... ]
function lsGet(k, def) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? def; } catch { return def; } }
function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }

// Seed from the prefs embedded at build time so the first paint is correct;
// initPrefs() then reconciles with the freshest source below.
let tracked = (DATA.prefs && DATA.prefs.tracked) || {};
let hidden = new Set((DATA.prefs && DATA.prefs.hidden) || []);
let showHidden = false;

// Following panel starts collapsed to a one-line summary; the "no longer
// available" roles within it stay collapsed even when the panel is expanded.
let trackedExpanded = false;
let goneExpanded = false;

// Jobs present in the current run, by id → used to detect tracked roles that
// have since vanished, and to refresh stored snapshots with the latest data.
const byId = new Map(DATA.jobs.map(j => [j.id, j]));

// Persist the current state to its backing store (live server if one answered,
// otherwise per-browser localStorage).
function persist() {
  if (serverPrefs) {
    fetch("/api/prefs", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tracked, hidden: [...hidden] }) }).catch(() => {});
  } else {
    lsSet(LS_TRACK, tracked);
    lsSet(LS_HIDE, [...hidden]);
  }
}

// Load the authoritative state, refresh live snapshots, then do the first paint.
async function initPrefs() {
  if (location.protocol.startsWith("http")) {
    try {
      const r = await fetch("/api/prefs");
      if (r.ok) { const p = await r.json();
        tracked = p.tracked || {}; hidden = new Set(p.hidden || []);
        serverPrefs = true; }
    } catch {}
  }
  if (!serverPrefs) {  // static host (GitHub Pages) or file:// → local fallback
    const t = lsGet(LS_TRACK, null), h = lsGet(LS_HIDE, null);
    if (t) tracked = t;
    if (h) hidden = new Set(h);
  }
  // Keep snapshots of still-live tracked roles current with the latest fetch.
  let dirty = false;
  for (const id of Object.keys(tracked)) {
    if (byId.has(id)) { tracked[id] = byId.get(id); dirty = true; }
  }
  if (dirty) persist();
  render();
}

function toggleTrack(id) {
  if (tracked[id]) delete tracked[id];
  else { const j = byId.get(id) || tracked[id]; if (j) tracked[id] = j; }
  persist();
  renderAll();
}
function toggleHide(id) {
  if (hidden.has(id)) hidden.delete(id); else hidden.add(id);
  persist();
  renderAll();
}
// One delegated listener handles every row's track / dismiss button.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.getAttribute("data-id");
  if (btn.dataset.act === "track") toggleTrack(id);
  else if (btn.dataset.act === "hide") toggleHide(id);
});
// Following-panel collapse/expand and the "no longer available" sub-toggle.
document.addEventListener("click", (e) => {
  if (e.target.closest("#trackedHead")) { trackedExpanded = !trackedExpanded; renderTracked(); return; }
  if (e.target.closest("#goneToggle")) { goneExpanded = !goneExpanded; renderTracked(); }
});

function actionsHtml(j, ctx) {
  const isTracked = !!tracked[j.id];
  const star = `<button class="iconbtn track${isTracked ? " on" : ""}" data-act="track" data-id="${esc(j.id)}" title="${isTracked ? "Stop following" : "Follow this role"}" aria-label="${isTracked ? "Stop following" : "Follow this role"}">${isTracked ? "★" : "☆"}</button>`;
  if (ctx === "tracked") return `<div class="acts">${star}</div>`;
  const isHidden = hidden.has(j.id);
  const drop = `<button class="iconbtn drop" data-act="hide" data-id="${esc(j.id)}" title="${isHidden ? "Restore to list" : "Not interested — hide this role"}" aria-label="${isHidden ? "Restore to list" : "Not interested"}">${isHidden ? "↩" : "✕"}</button>`;
  return `<div class="acts">${star}${drop}</div>`;
}

// Fallback for rows saved before work_type existed (e.g. old Following
// snapshots); the scraper classifies everything it fetches now.
function workTypeOf(j) {
  if (j.work_type) return j.work_type;
  const v = (j.location || "").toLowerCase();
  if (/\bhybrid\b/.test(v)) return "hybrid";
  if (/\bremote\b/.test(v)) return "remote";
  if (/\b(?:on[- ]?site|in[- ]office|office[- ]based)\b/.test(v)) return "onsite";
  return "unknown";
}
const WORK_TYPE_LABEL = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site", unknown: "Unknown" };

// The Work Type column already says remote/hybrid/on-site, so drop those words
// from the location pill ("USA - Remote" -> "USA").
function locationForDisplay(location) {
  return (location || "")
    .replace(/\b(?:remote|hybrid|on[- ]?site|in[- ]office|office[- ]based)\b/gi, "")
    .replace(/\s*[-|/]\s*/g, " ")
    .replace(/^[\s,;]+|[\s,;]+$/g, "")
    .replace(/\s{2,}/g, " ");
}

function rowHtml(j, ctx) {
  const gone = ctx === "tracked" && !byId.has(j.id);
  const badge = gone ? `<div class="badge gone">GONE</div>`
    : (j.isNew ? `<div class="badge">NEW</div>` : "");
  const type = workTypeOf(j);
  const typeChip = `<div class="chip ${type}">${WORK_TYPE_LABEL[type] || "Unknown"}</div>`;
  const shown = locationForDisplay(j.location);
  const loc = shown ? `<div class="chip location-chip" title="${esc(j.location)}">${esc(shown)}</div>` : "";
  const view = j.url ? `<a class="view" href="${esc(j.url)}" target="_blank" rel="noopener">View →</a>` : `<span class="c-view"></span>`;
  const cls = "row" + (gone ? " gone" : (j.isNew ? " new" : ""))
    + (ctx === "main" && hidden.has(j.id) ? " hiddenrow" : "");
  const upd = gone ? "no longer listed" : (j.updated || "—");
  return `<div class="${cls}">
    <div class="c-logo">${logoHtml(j.company, j.domain)}</div>
    <div class="c-role"><div class="title">${esc(j.title)}</div><div class="co">${esc(j.company)}</div></div>
    <div class="c-status">${badge}</div>
    <div class="c-type">${typeChip}</div>
    <div class="c-loc">${loc}</div>
    <div class="c-upd upd">${esc(upd)}</div>
    ${view}
    <div class="c-act">${actionsHtml(j, ctx)}</div>
  </div>`;
}

function renderTracked() {
  const items = Object.values(tracked);
  const panel = $("tracked");
  if (!items.length) { panel.style.display = "none"; return; }
  // Vanished roles float to the top so they catch the eye; then newest-first.
  items.sort((a, b) => (byId.has(b.id) ? 0 : 1) - (byId.has(a.id) ? 0 : 1)
    || (Number(b.isNew) - Number(a.isNew))
    || a.company.localeCompare(b.company));
  const liveItems = items.filter(j => byId.has(j.id));
  const goneItems = items.filter(j => !byId.has(j.id));
  panel.style.display = "block";
  $("trackedCt").textContent = items.length + (items.length === 1 ? " role" : " roles")
    + (goneItems.length ? ` · ${goneItems.length} no longer available` : "");

  $("trackedHead").setAttribute("aria-expanded", String(trackedExpanded));
  $("trackedCaret").classList.toggle("open", trackedExpanded);
  const rowsEl = $("trackedRows");
  rowsEl.style.display = trackedExpanded ? "block" : "none";
  if (!trackedExpanded) return;   // collapsed: skip rebuilding the (hidden) row HTML

  const goneHtml = goneItems.length
    ? `<button class="gone-toggle" id="goneToggle" type="button" aria-expanded="${goneExpanded}" aria-controls="trackedRows">
        <span>${goneItems.length} no longer available</span>
        <svg class="car${goneExpanded ? " open" : ""}" width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 4l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"></path></svg>
      </button>${goneExpanded ? goneItems.map(j => rowHtml(j, "tracked")).join("") : ""}`
    : "";
  rowsEl.innerHTML = liveItems.map(j => rowHtml(j, "tracked")).join("") + goneHtml;
}

function render() {
  renderTracked();
  const q = $("search").value.trim().toLowerCase();
  const co = sel.value;
  const lf = $("loc").value;
  const kwRe = keywordRegex(getEffectiveKeywords());
  const rows = DATA.jobs.filter(j => {
    if (tracked[j.id]) return false;                 // shown in the Following panel
    if (!showHidden && hidden.has(j.id)) return false;
    if (showHidden && !hidden.has(j.id)) return false;
    if (co && j.company !== co) return false;
    if (lf) {
      const type = workTypeOf(j);
      if (lf === "other" ? (type === "remote" || type === "hybrid") : type !== lf) return false;
    }
    if (kwRe && !kwRe.test(j.title)) return false;
    if (q && !(j.title + " " + j.company + " " + j.location).toLowerCase().includes(q)) return false;
    return true;
  });
  $("bannerCt").textContent = rows.length + " of " + DATA.total_jobs + " jobs";
  $("rows").innerHTML = rows.map(j => rowHtml(j, "main")).join("");
  const emptyEl = $("empty");
  emptyEl.style.display = rows.length ? "none" : "block";
  emptyEl.textContent = showHidden
    ? "Nothing hidden yet — use ✕ on a role to mark it as not interested."
    : (keywordOverride() !== null
      ? "No jobs match your keywords. Edit them or use Reset to restore the config.json list."
      : "No jobs match your current filters.");

  // "Show hidden" toggle reflects the current count.
  const hb = $("hideToggle");
  if (hidden.size) {
    hb.style.display = "inline-flex";
    hb.classList.toggle("on", showHidden);
    hb.textContent = (showHidden ? "Hide dismissed · " : "Show dismissed · ") + hidden.size;
  } else {
    hb.style.display = "none";
    showHidden = false;
  }
}
const renderAll = render;
$("hideToggle").addEventListener("click", () => { showHidden = !showHidden; render(); });
$("search").addEventListener("input", render);
sel.addEventListener("change", render);
$("loc").addEventListener("change", () => {
  lsSet(LS_FILTERS, { work_arrangement: $("loc").value || "any" });
  render();
});

// ---- Keyword + work-location filters (browser-local) ------------------------
// The scraper only keeps roles whose title matches config.json's keywords, so
// these narrow what it fetched: removing a keyword hides its roles, and a new
// keyword only matches roles that also matched a config keyword. Edits live in
// this browser's localStorage and never touch config.json.
const LS_KEYWORDS = "jt_keywords";  // [ keyword, ... ]; absent = use config.json
const LS_FILTERS  = "jt_filters";   // { work_arrangement: "any"|"remote"|"hybrid"|"other" }
const configKeywords = () => uniqueKeywords((DATA.filters && DATA.filters.keywords) || []);

// null when there's no valid override (so config.json applies); [] is a real
// "no keywords" choice that shows every fetched role.
function keywordOverride() {
  const v = lsGet(LS_KEYWORDS, null);
  return Array.isArray(v) ? uniqueKeywords(v) : null;
}
function getEffectiveKeywords() { return keywordOverride() ?? configKeywords(); }

function uniqueKeywords(list) {
  const seen = new Set(), out = [];
  for (const item of list) {
    const v = String(item ?? "").trim();
    if (v && !seen.has(v.toLowerCase())) { seen.add(v.toLowerCase()); out.push(v); }
  }
  return out;
}

// Same semantics as the scraper's filter (scraper/filters.py): whole words,
// case-insensitive, matched against the title only, so "ui" never hits "Build".
function keywordRegex(keywords) {
  if (!keywords.length) return null;
  const alts = keywords.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  return new RegExp(`\\b(?:${alts})\\b`, "i");
}

const keywordTagsEl = $("keywordTags");
const keywordInputEl = $("keywordInput");

function setKeywords(list) {
  const next = uniqueKeywords(list);
  const same = next.length === configKeywords().length
    && next.every((k, i) => k.toLowerCase() === configKeywords()[i].toLowerCase());
  // Matching config.json again is the same as having no override.
  if (same) { try { localStorage.removeItem(LS_KEYWORDS); } catch {} }
  else lsSet(LS_KEYWORDS, next);
  renderKeywordTags();
  render();
}

function renderKeywordTags() {
  const tags = getEffectiveKeywords();
  keywordTagsEl.querySelectorAll(".keyword-tag").forEach(el => el.remove());
  for (const tag of tags) {
    const el = document.createElement("span");
    el.className = "keyword-tag";
    const label = document.createElement("span");
    label.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "keyword-tag-remove";
    remove.textContent = "×";
    remove.title = remove.ariaLabel = `Remove ${tag}`;
    remove.addEventListener("click", () =>
      setKeywords(getEffectiveKeywords().filter(k => k.toLowerCase() !== tag.toLowerCase())));
    el.append(label, remove);
    keywordTagsEl.insertBefore(el, keywordInputEl);
  }
  $("keywordReset").hidden = keywordOverride() === null;
}

function addKeywords(raw) {
  const additions = String(raw || "").split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
  keywordInputEl.value = "";
  if (additions.length) setKeywords([...getEffectiveKeywords(), ...additions]);
}

keywordInputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === "," || e.key === ";") {
    e.preventDefault();
    addKeywords(keywordInputEl.value);
  } else if (e.key === "Backspace" && keywordInputEl.value === "") {
    const current = getEffectiveKeywords();
    if (current.length) { e.preventDefault(); setKeywords(current.slice(0, -1)); }
  }
});
// Commit a half-typed keyword when focus leaves, without pulling focus back.
keywordInputEl.addEventListener("blur", () => {
  if (keywordInputEl.value.trim()) addKeywords(keywordInputEl.value);
});
keywordInputEl.addEventListener("paste", (e) => {
  const text = (e.clipboardData || window.clipboardData).getData("text");
  if (/[\n,;]/.test(text)) { e.preventDefault(); addKeywords(keywordInputEl.value + text); }
});
$("keywordReset").addEventListener("click", () => {
  try { localStorage.removeItem(LS_KEYWORDS); } catch {}
  renderKeywordTags();
  render();
});

renderKeywordTags();
{
  const saved = (lsGet(LS_FILTERS, {}) || {}).work_arrangement;
  $("loc").value = ["remote", "hybrid", "other"].includes(saved) ? saved : "";
}

// Refresh: over HTTP via serve.py it triggers a real re-fetch, then reloads.
// On a static host (GitHub Pages) or file://, there's no backend to re-scrape,
// so it just reloads the latest published page instead of reporting a failure.
$("refresh").addEventListener("click", async () => {
  const b = $("refresh");
  if (b.classList.contains("busy")) return;
  b.classList.add("busy"); $("refreshLabel").textContent = "Refreshing…";
  if (location.protocol.startsWith("http")) {
    try {
      const r = await fetch("/api/refresh", { method: "POST" });
      // No backend on this host (e.g. GitHub Pages): the endpoint doesn't
      // exist, so just reload the published page rather than showing a failure.
      if (r.status === 404 || r.status === 405) { location.reload(); return; }
      if (!r.ok) throw new Error(r.status);
    } catch (e) {
      $("refreshLabel").textContent = "Refresh failed";
      b.classList.remove("busy");
      return;
    }
  } else {
    await new Promise(res => setTimeout(res, 400));
  }
  location.reload();
});

initPrefs();
