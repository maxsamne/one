const TIERS = ["ultra_cheap", "cheap", "default", "pro"];
const MODES = ["persistent", "conversational"];

let _markedInstance = null;
function getMarked() {
  if (_markedInstance) return _markedInstance;
  if (typeof window.marked === "undefined") return null;
  const { Marked } = window.marked;
  if (typeof window.markedHighlight !== "undefined" && typeof hljs !== "undefined") {
    const { markedHighlight } = window.markedHighlight;
    _markedInstance = new Marked(markedHighlight({
      langPrefix: "hljs language-",
      highlight(code, lang) {
        const language = hljs.getLanguage(lang) ? lang : "plaintext";
        return hljs.highlight(code, { language }).value;
      },
    }));
  } else {
    _markedInstance = new Marked();
  }
  return _markedInstance;
}

const PROMPT_MAX_LINES = 2;

const state = {
  tier: "ultra_cheap",
  tierManual: false,
  tasks: 0,
  tokensIn: 0,
  tokensOut: 0,
  costUsd: 0,
  // Skill catalog populated on load from GET /skills.
  skills: [],
  // Grader catalog (GET /graders) and project preset catalog (GET /presets).
  graders: [],
  presets: [],
  // Per-prompt attachments cleared on submit.
  attachedSkills: [],   // list of skill paths
  attachedGraders: [],  // list of grader paths
  attachedImages: [],   // list of {dataUri, name, mime, size, thumb}
  attachedParentId: null,  // task_id of the parent task this follow-up resumes from
  mode: "",                // "" = auto, "conversational", "persistent"
  // Autocomplete dropdown UI state. `kind` = "skill" | "grader" | "parent".
  dropdown: { open: false, items: [], active: 0, query: "", kind: "skill" },
};

const MAX_IMAGES = 8;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ACCEPTED_MIMES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

function promptLineHeightPx(el, cs) {
  const lh = parseFloat(cs.lineHeight);
  if (Number.isFinite(lh) && lh > 0) return lh;
  const fs = parseFloat(cs.fontSize);
  return Number.isFinite(fs) ? fs * 1.3 : 16;
}

function clampPromptHeight() {
  const ta = document.getElementById("prompt");
  const shell = document.getElementById("prompt-shell");
  if (!ta) return;
  const cs = getComputedStyle(ta);
  const lh = promptLineHeightPx(ta, cs);
  const pt = parseFloat(cs.paddingTop) || 0;
  const pb = parseFloat(cs.paddingBottom) || 0;
  const minH = lh + pt + pb;
  const maxH = lh * PROMPT_MAX_LINES + pt + pb;
  ta.style.height = "auto";
  const sh = Math.max(ta.scrollHeight, minH);
  const h = `${Math.min(sh, maxH)}px`;
  ta.style.height = h;
  ta.style.overflowY = sh > maxH ? "auto" : "hidden";
  if (shell) shell.style.height = h;
  updatePromptBackdrop();
}

function promptHighlightedHtml(text) {
  const re = /\/(ultra_cheap|cheap|default|pro)\b|--\s*(persistent|conversational)\b/gi;
  let out = "";
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    out += escapeHtml(text.slice(last, m.index));
    out += `<span class="at-tier">${escapeHtml(m[0])}</span>`;
    last = m.index + m[0].length;
  }
  out += escapeHtml(text.slice(last));
  return out;
}

function updatePromptBackdrop() {
  const ta = document.getElementById("prompt");
  const bd = document.getElementById("prompt-backdrop");
  if (!ta || !bd) return;
  bd.innerHTML = promptHighlightedHtml(ta.value);
  bd.style.transform = `translateY(-${ta.scrollTop}px)`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function parseCost(str) {
  const n = parseFloat(String(str).trim().replace(/^[$<]+/, ""));
  return Number.isFinite(n) ? n : 0;
}

function fmtCost(usd) {
  if (usd === 0) return "$0.00";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(3)}`;
}

function parseTierPrefix(raw) {
  if (!raw.startsWith("/")) return { tier: null, task: raw };
  const parts = raw.split(/\s+/, 2);
  const cand = parts[0].slice(1).toLowerCase();
  if (TIERS.includes(cand)) {
    const rest = parts.length > 1 ? parts[1].trim() : "";
    return { tier: cand, task: rest };
  }
  return { tier: null, task: raw };
}

const AT_TIER_RE = /\/(ultra_cheap|cheap|default|pro)\b/gi;
const MODE_FLAG_RE = /--\s*(persistent|conversational)\b/gi;

function lastAtTierInText(text) {
  let m;
  let last = null;
  AT_TIER_RE.lastIndex = 0;
  while ((m = AT_TIER_RE.exec(text)) !== null) {
    last = m[1].toLowerCase();
  }
  return last;
}

function syncTierFromPrompt() {
  const text = document.getElementById("prompt").value;
  if (!text.trim()) {
    state.tierManual = false;
    if (state.tier !== "ultra_cheap") {
      state.tier = "ultra_cheap";
      renderTierRow();
      renderSession();
    }
    return;
  }
  const t = lastAtTierInText(text);
  if (t) {
    state.tierManual = false;
    if (t !== state.tier) {
      state.tier = t;
      renderTierRow();
      renderSession();
    }
    return;
  }
  if (state.tierManual) return;
  if (state.tier !== "ultra_cheap") {
    state.tier = "ultra_cheap";
    renderTierRow();
    renderSession();
  }
}

function lastModeFlagInText(text) {
  let m;
  let last = null;
  MODE_FLAG_RE.lastIndex = 0;
  while ((m = MODE_FLAG_RE.exec(text)) !== null) {
    last = m[1].toLowerCase();
  }
  return last;
}

function syncModeFromPrompt() {
  const text = document.getElementById("prompt").value;
  const mode = lastModeFlagInText(text);
  if (!mode || !MODES.includes(mode)) return;
  if (mode !== state.mode) {
    state.mode = mode;
    document.getElementById("mode-select").value = mode;
  }
}

function stripTierMentions(text) {
  return text
    .replace(/\/(ultra_cheap|cheap|default|pro)\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function stripModeMentions(text) {
  return text
    .replace(/--\s*(persistent|conversational)\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function renderSession() {
  const el = document.getElementById("session-stats");
  const w = state.tasks === 1 ? "task" : "tasks";
  const tierLabel = escapeHtml(state.tier.replace(/_/g, " "));
  const cost = escapeHtml(fmtCost(state.costUsd));
  el.innerHTML = `
    <span class="status-sep">|</span>
    <span class="status-em">${cost}</span>
    <span class="status-sep">|</span>
    <span class="status-dim">${state.tasks} ${w}</span>
    <span class="status-sep">|</span>
    <span class="status-dim">${state.tokensIn.toLocaleString()} in · ${state.tokensOut.toLocaleString()} out</span>
    <span class="status-sep">|</span>
    <span class="status-dim">${tierLabel}</span>
  `;
}

function renderTierRow() {
  const row = document.getElementById("tier-row");
  row.innerHTML = TIERS.map(
    (t) =>
      `<button type="button" class="tier-btn${t === state.tier ? " active" : ""}" data-tier="${t}">${escapeHtml(t.replace(/_/g, " "))}</button>`
  ).join("");
  row.querySelectorAll(".tier-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.tier = btn.dataset.tier;
      state.tierManual = true;
      renderTierRow();
      renderSession();
    });
  });
}

function traceCatClass(cat) {
  const k = String(cat || "TOOL").replace(/[^A-Z0-9_]/gi, "");
  return k ? `cat-${k}` : "cat-TOOL";
}

function traceExtras(ev) {
  const skip = new Set([
    "type",
    "category",
    "message",
    "ts",
    "task_id",
    "level",
    "traceback",
  ]);
  const parts = [];
  for (const [k, v] of Object.entries(ev)) {
    if (skip.has(k) || v == null) continue;
    parts.push(`${k}=${String(v).slice(0, 72)}`);
  }
  return parts.join("  ");
}

function rowKeyForAgent(agentId) {
  // Bucket by logical role, not raw agent_id:
  // - "main": manager events (no agent_id) AND the top-level coder ("task_xyz:provider")
  // - "sub-abc123": each sub-agent gets its own row
  if (!agentId || agentId === "main") return "main";
  const idx = agentId.indexOf(":sub-");
  if (idx >= 0) return agentId.slice(idx + 1); // "sub-abc123"
  return "main";
}

function ensureAgentRow(trace, agentId) {
  const key = rowKeyForAgent(agentId);
  let row = trace.querySelector(`.trace-row[data-agent="${CSS.escape(key)}"]`);
  if (row) return row;

  const isSub = key.startsWith("sub-");
  row = document.createElement("div");
  row.className = `trace-row ${isSub ? "trace-row-sub" : "trace-row-main"}`;
  row.dataset.agent = key;

  // Sub-agent rows align under their parent's delegate cube. Pad-left by
  // (parent cell count) * (cell width + gap) so the first sub-cube sits
  // under the cube that spawned it.
  let leftPad = 0;
  if (isSub) {
    const parentGrid = trace.querySelector('.trace-row[data-agent="main"] .trace-grid');
    if (parentGrid) {
      const cellCount = parentGrid.querySelectorAll(".trace-cell").length;
      leftPad = cellCount * 12; // 9px cell + 3px gap
    }
  }

  row.innerHTML = `
    <div class="trace-row-label">${escapeHtml(key)}</div>
    <div class="trace-grid" style="${leftPad ? `padding-left:${leftPad}px;` : ""}"></div>
  `;
  trace.querySelector(".trace-rows").appendChild(row);
  return row;
}

function appendTrace(card, ev) {
  const cat = ev.category || "ERROR";
  const msg = ev.message || "";
  if (!cat && !msg) return;

  const trace = card.querySelector(".trace");

  // Init structure on first event: rows container + desc bar
  if (!trace.querySelector(".trace-rows")) {
    trace.innerHTML = `<div class="trace-rows"></div><div class="trace-desc"></div>`;
  }

  const agentId = ev.agent || "main";
  const rowKey = rowKeyForAgent(agentId);
  const row = ensureAgentRow(trace, agentId);
  const grid = row.querySelector(".trace-grid");
  const desc = trace.querySelector(".trace-desc");
  const extra = traceExtras(ev);
  const shortExtra = extra ? "  " + extra.slice(0, 80) : "";
  const label = `${cat}  ${msg}${shortExtra}`;

  // Deactivate previous active cell across ALL rows so only the latest event pulses
  trace.querySelectorAll(".trace-cell.active").forEach((c) => c.classList.remove("active"));

  const cell = document.createElement("div");
  cell.className = `trace-cell ${traceCatClass(cat)} active`;
  cell.dataset.cat = cat;
  cell.dataset.label = label;
  cell.dataset.agent = rowKey;

  const catVar = `var(--cat-${cat.toLowerCase() === "librarian" ? "lib" : cat.toLowerCase()})`;
  const fullHtml = `<span class="td-agent">${escapeHtml(rowKey)}</span><span class="td-cat" style="color:${catVar}">${escapeHtml(cat)}</span>${escapeHtml(msg)}${shortExtra ? `<span style="opacity:.7">  ${escapeHtml(extra)}</span>` : ""}`;
  cell.dataset.fullHtml = fullHtml;

  cell.addEventListener("mouseenter", () => {
    desc.classList.add("hover-mode");
    desc.innerHTML = fullHtml;
  });
  cell.addEventListener("mouseleave", () => {
    desc.classList.remove("hover-mode");
    desc.innerHTML = desc.dataset.latestHtml || "";
  });

  grid.appendChild(cell);
  requestAnimationFrame(() => cell.classList.add("filled"));

  // Always update the canonical "latest" — even while hovering. Only paint it
  // into the desc bar when the user isn't currently hovering a cell.
  desc.dataset.latestHtml = fullHtml;
  if (!desc.classList.contains("hover-mode")) {
    desc.innerHTML = fullHtml;
  }
}

function deriveArtifactSlug(html) {
  // Pull <title>…</title> if present; otherwise use first h1; otherwise "artifact".
  const title = html.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]
             || html.match(/<h1[^>]*>([^<]+)<\/h1>/i)?.[1]
             || "artifact";
  return title.trim().toLowerCase().slice(0, 40);
}

// Injected just before </body> in every artifact iframe. Sizes the iframe to actual
// content height so there's only ONE scroll axis (the outer .result panel) and no
// dead space below the real content.
//
// Important: artifacts often set `html, body { height: 100% }` (the standard "fill
// the viewport" pattern). Inside an iframe that makes scrollHeight report the
// iframe's own height — a feedback loop with the resize. We override height to auto
// so scrollHeight reports the *real* content extent, then resize the iframe to that.
const _IFRAME_RESIZE_SCRIPT = `
<script>
(function(){
  function unfill(){
    document.documentElement.style.height = 'auto';
    if (document.body) document.body.style.minHeight = '0';
  }
  function send(){
    unfill();
    var h = document.body ? document.body.scrollHeight : document.documentElement.scrollHeight;
    parent.postMessage({type:'one-iframe-height', frameId: window.name, height: h}, '*');
  }
  window.addEventListener('load', send);
  if (window.ResizeObserver) new ResizeObserver(send).observe(document.body || document.documentElement);
  // Fallback for late-loading content (fonts, images, lazy-rendered bits).
  setTimeout(send, 200); setTimeout(send, 800); setTimeout(send, 2000);
})();
</script>`;

let _iframeSeq = 0;

window.addEventListener("message", (e) => {
  const d = e.data;
  if (!d || d.type !== "one-iframe-height" || !d.frameId) return;
  const f = document.querySelector(`iframe[name="${CSS.escape(d.frameId)}"]`);
  if (!f) return;
  // Tight to actual content (was 200 min — caused empty space below short artifacts).
  // 4 px breathing room, capped at 4000 to stop a runaway page.
  const h = Math.min(Math.max(d.height + 4, 80), 4000);
  f.style.height = `${h}px`;
});

function injectIframeScript(html) {
  // Inject <base href> so root-relative paths (e.g. /images/...) resolve against
  // the gateway origin. Chrome does not inherit the parent's base URL in sandboxed
  // srcdoc iframes without allow-same-origin — explicit <base> fixes this.
  const base = `<base href="${window.location.origin}/">`;
  if (/<head(\s[^>]*)?>/i.test(html)) {
    html = html.replace(/<head(\s[^>]*)?>/i, (m) => m + base);
  } else {
    html = base + html;
  }
  // Insert resize script before </body> (or at end if no </body>).
  if (/<\/body>/i.test(html)) return html.replace(/<\/body>/i, `${_IFRAME_RESIZE_SCRIPT}</body>`);
  return html + _IFRAME_RESIZE_SCRIPT;
}

function rewriteGithubPagesImagePaths(html, taskId) {
  if (!taskId) return html;
  const assetBase = `/artifact-docs/${encodeURIComponent(taskId)}/images/`;
  return html.replaceAll("/one/images/", assetBase);
}

async function renderHtmlBlocks(container, taskId) {
  const blocks = container.querySelectorAll("pre code.language-html, pre code.hljs.language-html");
  for (const code of blocks) {
    const html = code.textContent;
    if (!html.trim()) continue;
    const previewHtml = rewriteGithubPagesImagePaths(html, taskId);
    const wrap = document.createElement("div");
    wrap.className = "html-artifact";

    const header = document.createElement("div");
    header.className = "html-artifact-bar";
    header.innerHTML = `<span class="html-artifact-label">interactive</span><a class="html-artifact-link" target="_blank" rel="noopener">open ↗</a>`;

    const iframe = document.createElement("iframe");
    iframe.className = "html-artifact-frame";
    iframe.setAttribute("sandbox", "allow-scripts allow-popups allow-forms");
    iframe.name = `one-iframe-${++_iframeSeq}`;  // identifier for postMessage routing
    iframe.srcdoc = injectIframeScript(previewHtml);

    wrap.appendChild(header);
    wrap.appendChild(iframe);
    code.closest("pre").replaceWith(wrap);

    // Persist server-side; non-blocking. Save the local-preview HTML, not the injected version.
    const slug = deriveArtifactSlug(html);
    fetch("/artifacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId, content: previewHtml, slug }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((res) => {
        if (res && res.url) header.querySelector(".html-artifact-link").href = res.url;
        else header.querySelector(".html-artifact-link").remove();
      })
      .catch(() => header.querySelector(".html-artifact-link").remove());
  }
}

async function finalizeCard(card, taskId, donePayload) {
  if (card.dataset.done === "1") return;
  card.dataset.done = "1";
  card.querySelector(".trace-cell.active")?.classList.remove("active");
  const status = donePayload.status || "done";
  const tokensIn = donePayload.tokens_in ?? 0;
  const tokensOut = donePayload.tokens_out ?? 0;
  const costStr = donePayload.cost || "$0.00";

  let result = "";
  let elapsed = "?";
  let error = "";
  let rec = null;
  try {
    const r = await fetch(`/tasks/${encodeURIComponent(taskId)}`);
    if (r.ok) {
      rec = await r.json();
      result = rec.result || "";
      elapsed = rec.elapsed_s ?? "?";
      error = rec.error || "";
    }
  } catch (_) {}

  state.tasks += 1;
  state.tokensIn += tokensIn;
  state.tokensOut += tokensOut;
  state.costUsd += parseCost(costStr);
  renderSession();
  invalidateParentCache();

  const meta = card.querySelector(".task-meta");
  const ok = status === "done";
  const icon = ok ? "✓" : "✗";
  // order matches topbar: cost · id · tokens · time · tier
  meta.textContent = `${costStr} · ${taskId.slice(0, 8)} · ${icon} ${tokensIn.toLocaleString()}↑ ${tokensOut.toLocaleString()}↓ · ${elapsed}s · ${card.dataset.tier}`;

  const cancelBtn = card.querySelector(".cancel-btn");
  if (cancelBtn) cancelBtn.remove();

  const out = card.querySelector(".result");
  out.classList.toggle("error", !ok);
  const text = ok ? result : error || result || status;
  const md = getMarked();
  if (ok && md) {
    out.innerHTML = md.parse(text);
    renderHtmlBlocks(out, taskId);
  } else {
    out.textContent = text;
  }

  const prEl = card.querySelector(".pr-link");
  const prUrl = rec?.pr_url;
  if (prEl && prUrl) {
    prEl.innerHTML = `<span class="pr-label">PR</span><a href="${escapeHtml(prUrl)}" target="_blank" rel="noopener">${escapeHtml(prUrl.replace("https://github.com/", ""))}</a>`;
  }
}

function wireCancel(card, taskId) {
  const actions = card.querySelector(".task-actions");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "cancel-btn";
  btn.textContent = "cancel";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await fetch(`/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
    } catch (_) {}
  });
  actions.appendChild(btn);
}

function openEventStream(taskId, card) {
  const es = new EventSource(`/tasks/${encodeURIComponent(taskId)}/events`);

  es.onmessage = (e) => {
    if (!e.data || !e.data.trim()) return;
    let ev;
    try {
      ev = JSON.parse(e.data);
    } catch {
      return;
    }
    if (ev.type === "done") {
      es.close();
      finalizeCard(card, taskId, ev);
      return;
    }
    if (ev.ui !== false) appendTrace(card, ev);
  };

  es.onerror = async () => {
    es.close();
    if (card.dataset.done === "1") return;
    // Was the task itself dropped (e.g. orphaned from a previous gateway process)?
    // GET /tasks/{id} returns 404 in that case — show a cleaner message.
    try {
      const r = await fetch(`/tasks/${encodeURIComponent(taskId)}`);
      if (r.status === 404) {
        card.dataset.done = "1";
        appendTrace(card, { category: "ERROR", message: "task no longer tracked (gateway restart)" });
        return;
      }
    } catch (_) { /* fall through to generic */ }
    appendTrace(card, {
      category: "ERROR",
      message: "event stream closed (reload page to reconnect)",
    });
  };
}

function addTaskCard(taskId, promptText, tier) {
  _knownTaskIds.add(taskId);
  const feed = document.getElementById("feed");
  const card = document.createElement("article");
  card.className = "task-card";
  card.dataset.tier = tier;
  card.dataset.done = "0";
  card.innerHTML = `
    <div class="task-head">
      <div class="task-head-top">
        <div class="task-meta">${escapeHtml(taskId.slice(0, 8))} · running… · ${escapeHtml(tier.replace(/_/g, " "))}</div>
        <div class="task-actions"></div>
      </div>
      <h2 class="task-title">${escapeHtml(promptText)}</h2>
    </div>
    <div class="trace" aria-label="Reasoning trace"></div>
    <div class="pr-link"></div>
    <div class="result" aria-label="Result"></div>
  `;
  feed.prepend(card);
  wireCancel(card, taskId);
  openEventStream(taskId, card);
  feed.scrollTop = 0;
}

// --------------------------------------------------------------------------
// Skill catalog + chips
// --------------------------------------------------------------------------

async function loadSkillCatalog() {
  try {
    const r = await fetch("/skills");
    if (r.ok) state.skills = await r.json();
  } catch (_) { /* no-op; UI degrades gracefully */ }
}

async function loadGraderCatalog() {
  try {
    const r = await fetch("/graders");
    if (r.ok) state.graders = await r.json();
  } catch (_) { /* no-op */ }
}

async function loadPresetCatalog() {
  try {
    const r = await fetch("/presets");
    if (r.ok) state.presets = await r.json();
  } catch (_) { /* no-op */ }
  renderPresetRow();
}

function graderLabel(path) {
  // "general/article-voice.md" -> "article-voice"
  const last = path.split("/").pop() || path;
  return last.replace(/\.md$/, "");
}

function renderPresetRow() {
  const row = document.getElementById("preset-row");
  if (!row) return;
  if (!state.presets.length) {
    row.hidden = true;
    return;
  }
  row.hidden = false;
  row.innerHTML = `<span class="preset-prefix">preset</span>` +
    state.presets.map((p) =>
      `<button type="button" class="preset-pill" data-name="${escapeHtml(p.name)}" title="${escapeHtml(p.description || "")}">${escapeHtml(p.name)}</button>`
    ).join("");
  row.querySelectorAll(".preset-pill").forEach((btn) => {
    btn.addEventListener("click", () => applyPreset(btn.dataset.name));
  });
}

function applyPreset(name) {
  const p = state.presets.find((x) => x.name === name);
  if (!p) return;
  state.tier = p.tier;
  state.tierManual = true;  // user picked a preset, don't auto-overwrite from prompt
  state.attachedSkills = [...p.skills];
  state.attachedGraders = [...p.graders];
  renderTierRow();
  renderSession();
  renderChips();
  renderSuggestBar([]);
}

function skillLabel(path) {
  // "general/artifact-design/SKILL.md" -> "artifact-design"
  // "general/python.md"                -> "python"
  const parts = path.split("/");
  const last = parts[parts.length - 1];
  if (last === "SKILL.md") return parts[parts.length - 2];
  return last.replace(/\.md$/, "");
}

function attachSkill(path) {
  if (state.attachedSkills.includes(path)) return;
  state.attachedSkills.push(path);
  renderChips();
  renderSuggestBar();
  suggestGradersForSkills();
}

function detachSkill(path) {
  state.attachedSkills = state.attachedSkills.filter((p) => p !== path);
  renderChips();
  renderSuggestBar();
}

function attachGrader(path) {
  if (state.attachedGraders.includes(path)) return;
  state.attachedGraders.push(path);
  renderChips();
  renderSuggestBar();
}

function detachGrader(path) {
  state.attachedGraders = state.attachedGraders.filter((p) => p !== path);
  renderChips();
}

async function suggestGradersForSkills() {
  if (!state.attachedSkills.length) return;
  try {
    const qs = encodeURIComponent(state.attachedSkills.join(","));
    const r = await fetch(`/graders/suggest?skills=${qs}`);
    if (!r.ok) return;
    const matches = await r.json();
    const novel = matches.filter((g) => !state.attachedGraders.includes(g.path));
    if (!novel.length) return;
    appendGraderSuggestions(novel);
  } catch (_) { /* ignore */ }
}

function appendGraderSuggestions(graderItems) {
  const bar = document.getElementById("suggest-bar");
  bar.hidden = false;
  // Preserve any existing skill suggestions; append a grader section after them.
  const existing = bar.innerHTML;
  const block = `<span class="suggest-prefix suggest-prefix-grader">add grader?</span>` +
    graderItems.map((g) =>
      `<button type="button" class="suggest-chip suggest-chip-grader" data-grader-path="${escapeHtml(g.path)}">+ ${escapeHtml(graderLabel(g.path))}</button>`
    ).join("");
  bar.innerHTML = existing + block;
  bar.querySelectorAll(".suggest-chip-grader").forEach((b) => {
    b.addEventListener("click", () => attachGrader(b.dataset.graderPath));
  });
}

function renderChips() {
  const row = document.getElementById("chips-row");
  row.innerHTML = "";
  const empty = state.attachedSkills.length === 0 &&
                state.attachedGraders.length === 0 &&
                !state.attachedParentId;
  if (empty) {
    row.hidden = true;
    return;
  }
  row.hidden = false;
  if (state.attachedParentId) {
    const chip = document.createElement("span");
    chip.className = "chip chip-parent";
    chip.title = `Continue from task ${state.attachedParentId}`;
    chip.innerHTML = `↩ ${escapeHtml(state.attachedParentId.slice(0, 8))}<button type="button" class="chip-x" aria-label="Detach">×</button>`;
    chip.querySelector(".chip-x").addEventListener("click", () => {
      state.attachedParentId = null;
      renderChips();
    });
    row.appendChild(chip);
  }
  for (const path of state.attachedSkills) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.title = path;
    chip.innerHTML = `${escapeHtml(skillLabel(path))}<button type="button" class="chip-x" aria-label="Remove">×</button>`;
    chip.querySelector(".chip-x").addEventListener("click", () => detachSkill(path));
    row.appendChild(chip);
  }
  for (const path of state.attachedGraders) {
    const chip = document.createElement("span");
    chip.className = "chip chip-grader";
    chip.title = `grader: ${path}`;
    chip.innerHTML = `⚖ ${escapeHtml(graderLabel(path))}<button type="button" class="chip-x" aria-label="Remove">×</button>`;
    chip.querySelector(".chip-x").addEventListener("click", () => detachGrader(path));
    row.appendChild(chip);
  }
}

// --------------------------------------------------------------------------
// Image attachments — paste, drop, file picker, thumbnails
// --------------------------------------------------------------------------

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function attachImageFiles(files) {
  for (const file of files) {
    if (!ACCEPTED_MIMES.has(file.type)) {
      alert(`Skipping ${file.name}: only PNG/JPEG/WEBP/GIF allowed.`);
      continue;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      alert(`Skipping ${file.name}: exceeds ${MAX_IMAGE_BYTES / (1024 * 1024)} MB.`);
      continue;
    }
    if (state.attachedImages.length >= MAX_IMAGES) {
      alert(`Max ${MAX_IMAGES} images per task.`);
      break;
    }
    try {
      const dataUri = await readFileAsDataURL(file);
      state.attachedImages.push({
        dataUri, name: file.name, mime: file.type, size: file.size, thumb: dataUri,
      });
    } catch (_) { /* ignore */ }
  }
  renderThumbs();
}

function detachImage(idx) {
  state.attachedImages.splice(idx, 1);
  renderThumbs();
}

function renderThumbs() {
  const row = document.getElementById("thumbs-row");
  row.innerHTML = "";
  if (state.attachedImages.length === 0) {
    row.hidden = true;
    return;
  }
  row.hidden = false;
  state.attachedImages.forEach((img, idx) => {
    const t = document.createElement("div");
    t.className = "thumb";
    t.title = `${img.name} (${(img.size / 1024).toFixed(1)} KB)`;
    t.style.backgroundImage = `url("${img.thumb}")`;
    const x = document.createElement("button");
    x.className = "thumb-x";
    x.type = "button";
    x.textContent = "×";
    x.setAttribute("aria-label", "Remove image");
    x.addEventListener("click", () => detachImage(idx));
    t.appendChild(x);
    row.appendChild(t);
  });
}

// --------------------------------------------------------------------------
// Skill autocomplete dropdown
// --------------------------------------------------------------------------

function fuzzyFilterSkills(q) {
  const ql = q.toLowerCase();
  if (!ql) return state.skills.slice(0, 20);
  return state.skills.filter((s) => {
    const fields = [s.path, s.summary, ...(s.keywords || [])].join(" ").toLowerCase();
    return fields.includes(ql);
  });
}

function fuzzyFilterGraders(q) {
  const ql = q.toLowerCase();
  if (!ql) return state.graders.slice(0, 20);
  return state.graders.filter((g) => {
    const fields = [g.path, g.summary, ...(g.suggested_for_skills || [])].join(" ").toLowerCase();
    return fields.includes(ql);
  });
}

function openDropdown(items, query = "", kind = "skill") {
  const dd = document.getElementById("dropdown");
  state.dropdown = { open: true, items, active: 0, query, kind };
  const labelFn = kind === "grader" ? graderLabel : skillLabel;
  if (items.length === 0) {
    dd.innerHTML = `<div class="dropdown-empty">no matching ${escapeHtml(kind)}s</div>`;
    dd.hidden = false;
    return;
  }
  dd.innerHTML = items
    .map((s, i) => `
      <div class="dropdown-item${i === 0 ? " active" : ""}" data-idx="${i}" role="option">
        <div class="dropdown-item-path">${escapeHtml(labelFn(s.path))} <span style="opacity:.5">— ${escapeHtml(s.path)}</span></div>
        <div class="dropdown-item-summary">${escapeHtml(s.summary || "")}</div>
      </div>`)
    .join("");
  dd.hidden = false;
  dd.querySelectorAll(".dropdown-item").forEach((el) => {
    el.addEventListener("click", () => selectDropdownItem(parseInt(el.dataset.idx, 10)));
  });
}

function closeDropdown() {
  state.dropdown.open = false;
  document.getElementById("dropdown").hidden = true;
}

function moveDropdownActive(delta) {
  if (!state.dropdown.open || state.dropdown.items.length === 0) return;
  const dd = document.getElementById("dropdown");
  const next = (state.dropdown.active + delta + state.dropdown.items.length) % state.dropdown.items.length;
  state.dropdown.active = next;
  dd.querySelectorAll(".dropdown-item").forEach((el, i) => el.classList.toggle("active", i === next));
  const activeEl = dd.querySelector(".dropdown-item.active");
  if (activeEl) activeEl.scrollIntoView({ block: "nearest" });
}

function selectDropdownItem(idx) {
  const item = state.dropdown.items[idx];
  if (item) {
    if (state.dropdown.kind === "grader") attachGrader(item.path);
    else attachSkill(item.path);
    // If the dropdown was opened by `/<query>` typing, strip that token from the textarea.
    stripSlashTokenIfPresent(state.dropdown.query);
  }
  closeDropdown();
  document.getElementById("prompt").focus();
}

function stripSlashTokenIfPresent(query) {
  if (!query) return;
  const ta = document.getElementById("prompt");
  const re = new RegExp(`/${query.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}\\b`, "i");
  // Strip the slash token but preserve a trailing space so the user can keep typing
  // without their next character butting up against the previous word.
  ta.value = ta.value.replace(re, "").replace(/[ \t]{2,}/g, " ").replace(/^\s+/, "");
  syncTierFromPrompt();
  syncModeFromPrompt();
  clampPromptHeight();
}

function detectSlashSkillQuery(text) {
  // Look for the LAST "/<word>" near the cursor that is NOT a tier name.
  // Returns {kind, query} or null.
  const m = text.match(/\/([a-z][a-z0-9_-]*)$/i);
  if (!m) return null;
  const candidate = m[1].toLowerCase();
  if (candidate === "grader" || candidate === "graders") return { kind: "grader", query: "" };
  if (candidate === "skill" || candidate === "skills") return { kind: "skill", query: "" };
  if (TIERS.includes(candidate) || TIERS.some((t) => t.startsWith(candidate))) return null;
  return { kind: "skill", query: candidate };
}

// --------------------------------------------------------------------------
// Inline suggest bar — debounced server-side keyword match
// --------------------------------------------------------------------------

let _suggestTimer = null;
let _suggestSeq = 0;

function scheduleSuggest() {
  clearTimeout(_suggestTimer);
  _suggestTimer = setTimeout(runSuggest, 250);
}

async function runSuggest() {
  const text = document.getElementById("prompt").value.trim();
  if (text.length < 4) {
    renderSuggestBar([]);
    return;
  }
  const seq = ++_suggestSeq;
  try {
    const r = await fetch(`/skills/suggest?q=${encodeURIComponent(text)}`);
    if (!r.ok) return;
    const matches = await r.json();
    if (seq !== _suggestSeq) return;  // a newer query overtook us
    const novel = matches.filter((s) => !state.attachedSkills.includes(s.path));
    renderSuggestBar(novel);
  } catch (_) { /* ignore */ }
}

function renderSuggestBar(items) {
  const bar = document.getElementById("suggest-bar");
  if (items === undefined) items = state._lastSuggestions || [];
  state._lastSuggestions = items;
  // Filter out anything already attached.
  const novel = items.filter((s) => !state.attachedSkills.includes(s.path));
  if (novel.length === 0) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }
  bar.hidden = false;
  bar.innerHTML = `<span class="suggest-prefix">add skill?</span>` +
    novel.map((s) =>
      `<button type="button" class="suggest-chip" data-path="${escapeHtml(s.path)}">+ ${escapeHtml(skillLabel(s.path))}</button>`
    ).join("");
  bar.querySelectorAll(".suggest-chip").forEach((b) => {
    b.addEventListener("click", () => attachSkill(b.dataset.path));
  });
}

async function submit() {
  const ta = document.getElementById("prompt");
  const send = document.getElementById("send");
  let raw = ta.value.trim();
  if (!raw) return;

  syncTierFromPrompt();
  syncModeFromPrompt();

  const parsed = parseTierPrefix(raw);
  if (parsed.tier) {
    state.tierManual = false;
    state.tier = parsed.tier;
    renderTierRow();
    renderSession();
    raw = parsed.task.trim();
  }
  raw = stripTierMentions(raw).trim();
  raw = stripModeMentions(raw).trim();
  if (!raw) {
    ta.value = "";
    state.tierManual = false;
    state.mode = "";
    document.getElementById("mode-select").value = "";
    syncTierFromPrompt();
    clampPromptHeight();
    return;
  }

  send.disabled = true;
  try {
    const body = {
      task: raw,
      tier: state.tier,
      skills: [...state.attachedSkills],
      graders: [...state.attachedGraders],
      images: state.attachedImages.map((i) => i.dataUri),
    };
    if (state.attachedParentId) body.parent_task_id = state.attachedParentId;
    if (state.mode) body.mode = state.mode;
    const r = await fetch("/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(err.detail || `HTTP ${r.status}`);
      return;
    }
    const { task_id: taskId } = await r.json();
    const submittedTier = state.tier;
    ta.value = "";
    state.tierManual = false;
    state.attachedSkills = [];
    state.attachedGraders = [];
    state.attachedImages = [];
    state.attachedParentId = null;
    state.mode = "";
    document.getElementById("mode-select").value = "";
    renderChips();
    renderThumbs();
    renderSuggestBar([]);
    closeDropdown();
    syncTierFromPrompt();
    clampPromptHeight();
    addTaskCard(taskId, raw, submittedTier);
  } catch (e) {
    alert(String(e));
  } finally {
    send.disabled = false;
  }
}

document.getElementById("send").addEventListener("click", submit);

// "+G" button → open the grader autocomplete dropdown.
document.getElementById("chip-add-grader").addEventListener("click", () => {
  if (state.dropdown.open) {
    closeDropdown();
  } else {
    openDropdown(fuzzyFilterGraders(""), "", "grader");
  }
});

const promptEl = document.getElementById("prompt");
promptEl.addEventListener("input", async () => {
  syncTierFromPrompt();
  syncModeFromPrompt();
  clampPromptHeight();
  const text = promptEl.value;
  // `@<query>` opens the parent-task picker (DB-backed, restart-safe).
  const atQuery = detectAtParentQuery(text);
  if (atQuery !== null) {
    if (state.dropdown.open) closeDropdown();
    const tasks = await fetchRecentDoneTasks();
    renderParentDropdownItems(tasks, atQuery);
    return;
  }
  // If the @-picker was open and the user typed past `@<word>`, dismiss it.
  const dd = document.getElementById("dropdown");
  if (!dd.hidden && dd.dataset.kind === "parent") {
    dd.hidden = true;
    dd.dataset.kind = "";
  }
  // Slash-skill or slash-grader autocomplete near cursor.
  const hit = detectSlashSkillQuery(text);
  if (hit !== null) {
    if (hit.kind === "grader") openDropdown(fuzzyFilterGraders(hit.query), hit.query, "grader");
    else openDropdown(fuzzyFilterSkills(hit.query), hit.query, "skill");
  } else if (state.dropdown.open) {
    closeDropdown();
  }
  scheduleSuggest();
});
promptEl.addEventListener("scroll", updatePromptBackdrop);
promptEl.addEventListener("keydown", (e) => {
  if (state.dropdown.open) {
    if (e.key === "ArrowDown") { e.preventDefault(); moveDropdownActive(1); return; }
    if (e.key === "ArrowUp")   { e.preventDefault(); moveDropdownActive(-1); return; }
    if (e.key === "Enter")     { e.preventDefault(); selectDropdownItem(state.dropdown.active); return; }
    if (e.key === "Escape")    { e.preventDefault(); closeDropdown(); return; }
  }
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    submit();
    return;
  }
  if (e.key === "Enter") {
    requestAnimationFrame(() => {
      clampPromptHeight();
      updatePromptBackdrop();
    });
  }
});

// Paste handler — image clipboard data becomes an attachment.
promptEl.addEventListener("paste", async (e) => {
  const items = e.clipboardData?.items || [];
  const files = [];
  for (const it of items) {
    if (it.kind === "file") {
      const f = it.getAsFile();
      if (f) files.push(f);
    }
  }
  if (files.length) {
    e.preventDefault();
    await attachImageFiles(files);
  }
});

// File picker (chip-add button + hidden <input type="file">).
const fileInput = document.getElementById("file-input");
const chipAddBtn = document.getElementById("chip-add");
chipAddBtn.addEventListener("click", () => {
  // Open the dropdown with all skills; the user can also click "image" via separate keyboard shortcut.
  // Single + button does both: shift-click opens file picker, normal click opens skill dropdown.
  // Simpler: open skill dropdown by default. Image picking is via drag-drop or paste.
  if (state.dropdown.open) {
    closeDropdown();
  } else {
    openDropdown(fuzzyFilterSkills(""), "");
  }
});
fileInput.addEventListener("change", async (e) => {
  await attachImageFiles(Array.from(e.target.files || []));
  fileInput.value = "";
});
document.getElementById("mode-select").addEventListener("change", (e) => {
  state.mode = e.target.value;
});

// Drag-drop on the input panel — dashed-border feedback only, no overlay text.
const inputPanel = document.getElementById("input-panel");
let _dragDepth = 0;
inputPanel.addEventListener("dragenter", (e) => {
  if (!Array.from(e.dataTransfer?.types || []).includes("Files")) return;
  _dragDepth++;
  inputPanel.classList.add("dragover");
});
inputPanel.addEventListener("dragover", (e) => {
  if (Array.from(e.dataTransfer?.types || []).includes("Files")) e.preventDefault();
});
inputPanel.addEventListener("dragleave", () => {
  _dragDepth = Math.max(0, _dragDepth - 1);
  if (_dragDepth === 0) inputPanel.classList.remove("dragover");
});
inputPanel.addEventListener("drop", async (e) => {
  e.preventDefault();
  _dragDepth = 0;
  inputPanel.classList.remove("dragover");
  await attachImageFiles(Array.from(e.dataTransfer?.files || []));
});

// Click outside dropdown closes it.
document.addEventListener("click", (e) => {
  if (state.dropdown.open && !e.target.closest("#dropdown") && !e.target.closest("#chip-add") && !e.target.closest("#chip-add-grader") && e.target !== promptEl) {
    closeDropdown();
  }
  // Also dismiss the parent picker (different state path) on outside click.
  const dd = document.getElementById("dropdown");
  if (!dd.hidden && dd.dataset.kind === "parent" &&
      !e.target.closest("#dropdown") && !e.target.closest("#parent-add")) {
    dd.hidden = true;
    dd.dataset.kind = "";
  }
});

// --------------------------------------------------------------------------
// Parent task picker (@task) + Schedules modal
// --------------------------------------------------------------------------

// Short-lived cache so typing @abc doesn't hammer the endpoint on every keystroke.
let _parentCache = null;
let _parentCacheAt = 0;
const PARENT_CACHE_MS = 10_000;

async function fetchRecentDoneTasks(limit = 30) {
  if (_parentCache && (Date.now() - _parentCacheAt) < PARENT_CACHE_MS) return _parentCache;
  try {
    const r = await fetch(`/tasks/history?status=done&limit=${limit}`);
    if (!r.ok) return [];
    _parentCache = await r.json();
    _parentCacheAt = Date.now();
    return _parentCache;
  } catch (_) { return []; }
}

function invalidateParentCache() { _parentCache = null; }

function detectAtParentQuery(text) {
  // `@<word>` at end of input — case-insensitive, alphanumeric + hyphens/underscores.
  // `@` alone (no word yet) also opens the picker so it triggers immediately.
  const m = text.match(/@([a-z0-9_-]*)$/i);
  return m ? m[1].toLowerCase() : null;
}

function renderParentDropdownItems(tasks, query) {
  const dd = document.getElementById("dropdown");
  const q = (query || "").toLowerCase();
  const filtered = q
    ? tasks.filter((t) => t.task_id.toLowerCase().startsWith(q) || t.prompt.toLowerCase().includes(q))
    : tasks;
  if (filtered.length === 0) {
    dd.dataset.kind = "parent";
    dd.hidden = false;
    dd.innerHTML = `<div class="dropdown-empty">no matching tasks</div>`;
    return;
  }
  dd.dataset.kind = "parent";
  dd.hidden = false;
  dd.innerHTML = filtered.map((t) => {
    const ago = t.submitted_at ? fmtTimeAgo(t.submitted_at) : "";
    return `<div class="dropdown-item parent-item" data-parent="${escapeHtml(t.task_id)}">
      <div class="parent-item-meta">
        <code class="parent-item-id">${escapeHtml(t.task_id.slice(0, 8))}</code>
        <span class="parent-item-ago">${escapeHtml(ago)}</span>
      </div>
      <div class="parent-item-prompt">${escapeHtml(t.prompt)}</div>
    </div>`;
  }).join("");
  dd.querySelectorAll("[data-parent]").forEach((el) => {
    el.addEventListener("click", () => selectParentFromDropdown(el.dataset.parent));
  });
}

function selectParentFromDropdown(taskId) {
  state.attachedParentId = taskId;
  // Inherit tier, skills, graders, mode from the parent task so the follow-up
  // runs under the same defaults. User can still change anything before submitting.
  const parent = (_parentCache || []).find((t) => t.task_id === taskId);
  if (parent) {
    if (parent.tier) { state.tier = parent.tier; state.tierManual = true; }
    if (parent.skills?.length)  state.attachedSkills  = [...parent.skills];
    if (parent.graders?.length) state.attachedGraders = [...parent.graders];
    const inheritedMode = parent.mode || parent.mode_override;
    if (inheritedMode) {
      state.mode = inheritedMode;
      document.getElementById("mode-select").value = inheritedMode;
    }
  }
  // Strip the trailing `@<query>` token from the textarea so the prompt is clean.
  const ta = document.getElementById("prompt");
  ta.value = ta.value.replace(/@([a-z0-9_-]*)$/i, "");
  const dd = document.getElementById("dropdown");
  dd.hidden = true;
  dd.dataset.kind = "";
  renderChips();
  renderTierRow();
  clampPromptHeight();
  ta.focus();
}

function isParentDropdownOpen() {
  const dd = document.getElementById("dropdown");
  return !dd.hidden && dd.dataset.kind === "parent";
}

async function toggleParentPicker() {
  const dd = document.getElementById("dropdown");
  if (isParentDropdownOpen()) {
    dd.hidden = true;
    dd.dataset.kind = "";
    return;
  }
  invalidateParentCache();
  const tasks = await fetchRecentDoneTasks();
  if (tasks.length === 0) {
    alert("No completed tasks yet to follow up on.");
    return;
  }
  renderParentDropdownItems(tasks, "");
}

document.getElementById("parent-add").addEventListener("click", toggleParentPicker);

// --- Schedules modal ---

const SCHED_TIERS = TIERS.slice();

const _MONTHS = ["", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const _DOWS   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];  // croniter: 0 or 7 = Sun

function _describeField(raw, kind) {
  // kind: "minute" | "hour" | "dom" | "month" | "dow"
  if (raw === "*") return { every: true };
  // Step: */N or A-B/N — only handle the */N form for the "every N" phrasing.
  const step = raw.match(/^\*\/(\d+)$/);
  if (step) return { step: Number(step[1]) };
  // List or single value(s).
  if (/^[\d,-]+$/.test(raw)) {
    const parts = raw.split(",");
    const nums = [];
    for (const p of parts) {
      const r = p.match(/^(\d+)-(\d+)$/);
      if (r) {
        const [a, b] = [Number(r[1]), Number(r[2])];
        if (a <= b && b - a <= 60) for (let i = a; i <= b; i++) nums.push(i);
        else return { raw: true };
      } else if (/^\d+$/.test(p)) nums.push(Number(p));
      else return { raw: true };
    }
    return { values: nums };
  }
  return { raw: true };
}

function _fmtList(items, max = 4) {
  if (items.length <= max) {
    if (items.length <= 2) return items.join(" and ");
    return items.slice(0, -1).join(", ") + ", and " + items[items.length - 1];
  }
  return items.slice(0, max).join(", ") + `, +${items.length - max} more`;
}

function describeCron(expr) {
  const parts = (expr || "").trim().split(/\s+/);
  if (parts.length !== 5) return "custom schedule";
  const [mF, hF, domF, monF, dowF] = parts.map((p, i) =>
    _describeField(p, ["minute","hour","dom","month","dow"][i]));
  if ([mF,hF,domF,monF,dowF].some((f) => f.raw)) return "custom schedule (hover the field for raw expression)";

  // Time of day: combine minute + hour when both are single values or simple patterns.
  let timePart = "";
  if (mF.step && hF.every) timePart = `every ${mF.step} minute${mF.step === 1 ? "" : "s"}`;
  else if (mF.every && hF.every) timePart = "every minute";
  else if (mF.every && hF.step) timePart = `every minute, every ${hF.step} hour${hF.step === 1 ? "" : "s"}`;
  else if (mF.values && mF.values.length === 1 && hF.values && hF.values.length === 1) {
    const hh = String(hF.values[0]).padStart(2, "0");
    const mm = String(mF.values[0]).padStart(2, "0");
    timePart = `at ${hh}:${mm}`;
  }
  else if (mF.values && hF.every) timePart = `at minute ${_fmtList(mF.values)} of every hour`;
  else if (mF.values && mF.values.length === 1 && hF.values) {
    const mm = String(mF.values[0]).padStart(2, "0");
    timePart = `at ${_fmtList(hF.values.map((h) => `${String(h).padStart(2,"0")}:${mm}`))}`;
  }
  else timePart = `min=${parts[0]} hr=${parts[1]}`;

  // Day-of-week and day-of-month.
  let dayPart = "";
  if (!dowF.every && dowF.values) {
    const labels = dowF.values.map((n) => _DOWS[n % 7]);
    dayPart = `on ${_fmtList(labels)}`;
  }
  if (!domF.every && domF.values) {
    const dom = `on day ${_fmtList(domF.values.map(String))} of the month`;
    dayPart = dayPart ? `${dayPart} (${dom})` : dom;
  }

  // Month.
  let monthPart = "";
  if (!monF.every && monF.values) {
    monthPart = `in ${_fmtList(monF.values.map((n) => _MONTHS[n] || String(n)))}`;
  }

  // Defaults: if nothing constrains the day, it runs daily.
  if (!dayPart && !monthPart) dayPart = "daily";

  const tz = "(Europe/Stockholm)";
  return [timePart, dayPart, monthPart, tz].filter(Boolean).join(" ");
}

function fmtTimeAgo(ts) {
  if (!ts) return "never";
  const d = Date.now() / 1000 - ts;
  if (d < 60) return `${Math.round(d)}s ago`;
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  return `${Math.round(d / 86400)}d ago`;
}

function fmtTimeUntil(ts) {
  if (!ts) return "—";
  const d = ts - Date.now() / 1000;
  if (d < 0) return "due";
  if (d < 60) return `in ${Math.round(d)}s`;
  if (d < 3600) return `in ${Math.round(d / 60)}m`;
  if (d < 86400) return `in ${Math.round(d / 3600)}h`;
  return `in ${Math.round(d / 86400)}d`;
}

const schedState = {
  // Form field values — source of truth; DOM is synced from these.
  cron:    "",
  prompt:  "",
  mode:    "",
  tier:    "ultra_cheap",
  // Attachment lists (already state-owned).
  schedSkills:   [],
  schedGraders:  [],
  // UI state.
  skillsFilter: "",
  kind: "skill",
  editingId: null,
};

function setSchedFormMode(editing) {
  const submitBtn = document.querySelector("#sched-form .send-btn .send-btn__label");
  if (submitBtn) submitBtn.textContent = editing ? "Update" : "Save";
  document.getElementById("sched-cancel-edit").hidden = !editing;
}

function syncSchedFormToDOM() {
  document.getElementById("sched-cron").value   = schedState.cron;
  document.getElementById("sched-prompt").value = schedState.prompt;
  document.getElementById("sched-mode").value   = schedState.mode;
  document.getElementById("sched-tier").value   = schedState.tier;
}

function resetSchedForm() {
  schedState.editingId  = null;
  schedState.cron       = "";
  schedState.prompt     = "";
  schedState.mode       = "";
  schedState.tier       = "ultra_cheap";
  schedState.schedSkills  = [];
  schedState.schedGraders = [];
  syncSchedFormToDOM();
  document.getElementById("sched-nl").value = "";
  setSchedFormMode(false);
  renderSchedSkillsSummary();
  renderSchedSkillsList();
}

function startEditSchedule(s) {
  schedState.editingId    = s.id;
  schedState.cron         = s.cron    || "";
  schedState.prompt       = s.prompt  || "";
  schedState.mode         = s.mode    || "";
  schedState.tier         = s.tier    || "ultra_cheap";
  schedState.schedSkills  = [...(s.skills   || [])];
  schedState.schedGraders = [...(s.graders  || [])];
  syncSchedFormToDOM();
  setSchedFormMode(true);
  renderSchedSkillsSummary();
  renderSchedSkillsList();
  document.querySelector("#schedules-modal .modal-panel")?.scrollTo({ top: 0, behavior: "smooth" });
  document.getElementById("sched-prompt").focus();
}

function renderSchedTierSelect() {
  const sel = document.getElementById("sched-tier");
  sel.innerHTML = SCHED_TIERS.map((t) =>
    `<option value="${t}"${t === "ultra_cheap" ? " selected" : ""}>${escapeHtml(t.replace(/_/g, " "))}</option>`
  ).join("");
}

function renderSchedSkillsSummary() {
  const sEl = document.getElementById("sched-skills-summary");
  const ns = schedState.schedSkills.length;
  sEl.textContent = ns === 0 ? "no skills selected" : `${ns} skill${ns === 1 ? "" : "s"} selected`;
  const gEl = document.getElementById("sched-graders-summary");
  if (gEl) {
    const ng = schedState.schedGraders.length;
    gEl.textContent = ng === 0 ? "no graders selected" : `${ng} grader${ng === 1 ? "" : "s"} selected`;
  }
}

function renderSchedSkillsList() {
  const list = document.getElementById("sched-skills-list");
  const isGrader = schedState.kind === "grader";
  const items = isGrader ? state.graders : state.skills;
  const selected = isGrader ? schedState.schedGraders : schedState.schedSkills;
  const labelFn = isGrader ? graderLabel : skillLabel;
  const emptyMsg = isGrader ? "no graders available" : "no skills available";
  if (items.length === 0) {
    list.innerHTML = `<li class="sched-skills-empty">${emptyMsg}</li>`;
    return;
  }
  const q = schedState.skillsFilter.trim().toLowerCase();
  const matches = (s) => {
    if (!q) return true;
    const extras = isGrader ? (s.suggested_for_skills || []) : (s.keywords || []);
    const hay = `${s.path} ${s.domain || ""} ${s.summary || ""} ${extras.join(" ")}`.toLowerCase();
    return hay.includes(q);
  };
  const ordered = [...items].sort((a, b) => {
    const aSel = selected.includes(a.path) ? 0 : 1;
    const bSel = selected.includes(b.path) ? 0 : 1;
    return aSel - bSel;
  });
  const visible = ordered.filter((s) => selected.includes(s.path) || matches(s));
  if (visible.length === 0) {
    list.innerHTML = `<li class="sched-skills-empty">no matches</li>`;
    return;
  }
  list.innerHTML = visible.map((s) => {
    const checked = selected.includes(s.path);
    const label = isGrader ? labelFn(s.path) : `${s.domain || ""}/${labelFn(s.path)}`.replace(/^\//, "");
    return `<li class="sched-skill-item${checked ? " checked" : ""}" data-path="${escapeHtml(s.path)}" title="${escapeHtml(s.path)}">
      <span class="sched-skill-mark">${checked ? "✓" : ""}</span>
      <div class="sched-skill-text">
        <div class="sched-skill-path">${escapeHtml(label)}</div>
        <div class="sched-skill-summary">${escapeHtml(s.summary || "")}</div>
      </div>
    </li>`;
  }).join("");
  list.querySelectorAll(".sched-skill-item").forEach((el) => {
    el.addEventListener("click", () => {
      const path = el.dataset.path;
      const sel = schedState.kind === "grader" ? schedState.schedGraders : schedState.schedSkills;
      const i = sel.indexOf(path);
      if (i >= 0) sel.splice(i, 1);
      else sel.push(path);
      renderSchedSkillsList();
      renderSchedSkillsSummary();
    });
  });
}

function setSchedTab(kind) {
  schedState.kind = kind;
  document.querySelectorAll(".sched-tab").forEach((b) => {
    const active = b.dataset.kind === kind;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });
  renderSchedSkillsList();
}

async function loadSchedules() {
  const list = document.getElementById("sched-list");
  list.innerHTML = `<li class="sched-empty">loading…</li>`;
  try {
    const r = await fetch("/schedules");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const schedules = await r.json();
    if (schedules.length === 0) {
      list.innerHTML = `<li class="sched-empty">no schedules yet</li>`;
      return;
    }
    list.innerHTML = "";
    for (const s of schedules) {
      const li = document.createElement("li");
      li.className = "sched-item" + (s.enabled ? "" : " disabled");
      const modeTag = s.mode ? `<span class="sched-mode-tag">${escapeHtml(s.mode)}</span>` : "";
      li.innerHTML = `
        <div class="sched-item-head">
          <code class="sched-cron" title="${escapeHtml(describeCron(s.cron))}">${escapeHtml(s.cron)}</code>
          <span class="sched-tier-tag">${escapeHtml(s.tier.replace(/_/g, " "))}</span>
          ${modeTag}
          <span class="sched-times">last ${fmtTimeAgo(s.last_run_at)} · next ${fmtTimeUntil(s.next_run_at)}</span>
          <div class="sched-actions">
            <button type="button" data-edit="${escapeHtml(s.id)}">edit</button>
            <button type="button" data-toggle="${escapeHtml(s.id)}" data-enabled="${s.enabled ? 1 : 0}">${s.enabled ? "pause" : "enable"}</button>
            <button type="button" class="sched-del" data-del="${escapeHtml(s.id)}">delete</button>
          </div>
        </div>
        <div class="sched-prompt">${escapeHtml(s.prompt)}</div>
        ${s.skills.length ? `<div class="sched-skills">skills: ${s.skills.map((p) => escapeHtml(skillLabel(p))).join(", ")}</div>` : ""}
        ${(s.graders || []).length ? `<div class="sched-skills">graders: ${s.graders.map((p) => escapeHtml(graderLabel(p))).join(", ")}</div>` : ""}
      `;
      list.appendChild(li);
    }
    const byId = Object.fromEntries(schedules.map((s) => [s.id, s]));
    list.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const s = byId[btn.dataset.edit];
        if (s) startEditSchedule(s);
      });
    });
    list.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const enabled = btn.dataset.enabled !== "1";
        await fetch(`/schedules/${encodeURIComponent(btn.dataset.toggle)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
        });
        loadSchedules();
      });
    });
    list.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this schedule?")) return;
        await fetch(`/schedules/${encodeURIComponent(btn.dataset.del)}`, { method: "DELETE" });
        loadSchedules();
      });
    });
  } catch (e) {
    list.innerHTML = `<li class="sched-empty">failed to load: ${escapeHtml(String(e))}</li>`;
  }
}

function openSchedulesModal() {
  document.getElementById("schedules-modal").hidden = false;
  document.body.classList.add("modal-open");
  schedState.skillsFilter = "";
  document.getElementById("sched-skills-search").value = "";
  renderSchedTierSelect();
  resetSchedForm();
  setSchedTab("skill");
  loadSchedules();
}

function closeSchedulesModal() {
  document.getElementById("schedules-modal").hidden = true;
  document.body.classList.remove("modal-open");
}

document.getElementById("open-schedules").addEventListener("click", openSchedulesModal);
document.getElementById("sched-skills-search").addEventListener("input", (e) => {
  schedState.skillsFilter = e.target.value;
  renderSchedSkillsList();
});
document.querySelectorAll(".sched-tab").forEach((b) => {
  b.addEventListener("click", () => setSchedTab(b.dataset.kind));
});

async function nlToCron() {
  const nlEl = document.getElementById("sched-nl");
  const cronEl = document.getElementById("sched-cron");
  const goBtn = document.getElementById("sched-nl-go");
  const text = nlEl.value.trim();
  if (!text) return;
  goBtn.disabled = true;
  const orig = goBtn.textContent;
  goBtn.textContent = "…";
  try {
    const r = await fetch("/cron-from-nl", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(err.detail || `HTTP ${r.status}`);
      return;
    }
    const { cron } = await r.json();
    cronEl.value = cron;
    schedState.cron = cron;
    cronEl.focus();
  } finally {
    goBtn.disabled = false;
    goBtn.textContent = orig;
  }
}
document.getElementById("sched-nl-go").addEventListener("click", nlToCron);
document.getElementById("sched-nl").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); nlToCron(); }
});
document.querySelectorAll("#schedules-modal [data-close]").forEach((el) =>
  el.addEventListener("click", closeSchedulesModal)
);
// Esc closes the modal too.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("schedules-modal").hidden) {
    closeSchedulesModal();
  }
});
["sched-cron", "sched-prompt"].forEach((id) =>
  document.getElementById(id).addEventListener("input", (e) => {
    schedState[id === "sched-cron" ? "cron" : "prompt"] = e.target.value;
  })
);
document.getElementById("sched-mode").addEventListener("change", (e) => { schedState.mode = e.target.value; });
document.getElementById("sched-tier").addEventListener("change", (e) => { schedState.tier = e.target.value; });

document.getElementById("sched-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  schedState.cron = document.getElementById("sched-cron").value;
  schedState.prompt = document.getElementById("sched-prompt").value;
  const body = {
    cron:    schedState.cron.trim(),
    prompt:  schedState.prompt.trim(),
    tier:    schedState.tier,
    skills:  [...schedState.schedSkills],
    graders: [...schedState.schedGraders],
    mode:    schedState.mode || null,
  };
  if (!body.cron || !body.prompt) {
    alert("cron and prompt are required");
    return;
  }
  const editingId = schedState.editingId;
  const url = editingId ? `/schedules/${encodeURIComponent(editingId)}` : "/schedules";
  const method = editingId ? "PATCH" : "POST";
  if (!editingId) body.enabled = true;
  const r = await fetch(url, {
    method, headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    alert(err.detail || `HTTP ${r.status}`);
    return;
  }
  resetSchedForm();
  loadSchedules();
});

document.getElementById("sched-cancel-edit").addEventListener("click", resetSchedForm);

function addHistoricalCard(rec) {
  const feed = document.getElementById("feed");
  const card = document.createElement("article");
  card.className = "task-card task-card-historical";
  card.dataset.tier = rec.tier || "ultra_cheap";
  card.dataset.done = "1";
  const ok = rec.status === "done";
  const icon = ok ? "✓" : "✗";
  const elapsed = rec.elapsed_s ?? "?";
  const ago = rec.submitted_at ? fmtTimeAgo(rec.submitted_at) : "";
  card.innerHTML = `
    <div class="task-head">
      <div class="task-head-top">
        <div class="task-meta">${escapeHtml(rec.task_id.slice(0, 8))} · ${icon} ${elapsed}s · ${escapeHtml((rec.tier || "").replace(/_/g, " "))} · ${escapeHtml(ago)}</div>
        <div class="task-actions"></div>
      </div>
      <h2 class="task-title">${escapeHtml(rec.prompt)}</h2>
    </div>
    <div class="pr-link"></div>
    <div class="result" aria-label="Result"></div>
  `;
  const prEl = card.querySelector(".pr-link");
  if (prEl && rec.pr_url) {
    const prUrl = rec.pr_url;
    prEl.innerHTML = `<span class="pr-label">PR</span><a href="${escapeHtml(prUrl)}" target="_blank" rel="noopener">${escapeHtml(prUrl.replace("https://github.com/", ""))}</a>`;
  }
  const out = card.querySelector(".result");
  const text = ok ? (rec.result || "") : (rec.result || rec.status);
  out.classList.toggle("error", !ok);
  const md = getMarked();
  if (ok && md && text) {
    out.innerHTML = md.parse(text);
    renderHtmlBlocks(out, rec.task_id);
  } else {
    out.textContent = text;
  }
  feed.appendChild(card);
}

async function loadFeedHistory(limit = 5) {
  try {
    const r = await fetch(`/tasks/history?status=done&limit=${limit}`);
    if (!r.ok) return;
    const tasks = await r.json();
    // Render oldest-at-bottom so the feed reads naturally (newest tasks the user
    // submits this session prepend on top via addTaskCard).
    for (const t of tasks) {
      if (_knownTaskIds.has(t.task_id)) continue;
      _knownTaskIds.add(t.task_id);
      addHistoricalCard(t);
    }
  } catch (_) { /* non-fatal */ }
}

// --------------------------------------------------------------------------
// Live-tasks poller — picks up tasks started outside this session (cron fires,
// API clients, other browser tabs) and renders them in real time.
// --------------------------------------------------------------------------
const _knownTaskIds = new Set();
const POLL_LIVE_TASKS_MS = 5000;

async function pollLiveTasks() {
  for (const status of ["running", "queued"]) {
    try {
      const r = await fetch(`/tasks/history?status=${status}&limit=20`);
      if (!r.ok) continue;
      const tasks = await r.json();
      // Reverse so the oldest-among-new prepends first → newest ends up on top.
      for (const t of tasks.reverse()) {
        if (_knownTaskIds.has(t.task_id)) continue;
        _knownTaskIds.add(t.task_id);
        addTaskCard(t.task_id, t.prompt, t.tier || "ultra_cheap");
        invalidateParentCache();
      }
    } catch (_) { /* non-fatal */ }
  }
}

renderTierRow();
renderSession();
renderChips();
renderThumbs();
clampPromptHeight();
loadSkillCatalog();
loadGraderCatalog();
loadPresetCatalog();
loadFeedHistory();
pollLiveTasks();
setInterval(pollLiveTasks, POLL_LIVE_TASKS_MS);
