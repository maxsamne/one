> Design language for HTML artifacts — charts, dashboards, mini-sites, articles. Pulled in for any task that produces a chart, dashboard, mini-site, calculator, or interactive visualization rendered in the gateway's sandboxed iframe.

# Artifact design

## Keywords
<!-- Used by the gateway UI to suggest this skill when the user types matching words.
     Suggestions only — not auto-loaded. The user explicitly attaches skills via /skill or chips. -->
chart, charts, dashboard, dashboards, html, mini-site, minisite, visualization, visualisations, visualisation, interactive, plot, graph, infographic, artifact, calculator, web app, landing page, article, hero image, illustration

## Agent hints
- **Output:** complete self-contained HTML in a final ```html``` block — runs in a sandboxed iframe (CSP allows only cdnjs.cloudflare.com).
- **Preferred thinking:** simple chart → `low`, dashboard with state → `medium`.
- **Commonly related skills:** general/python.md (when generating data inline).
- **Hero images:** for article-shaped or report-style artifacts, call `generate_image(prompt)` to produce a hero/banner image if it genuinely improves the aesthetic — atmospheric, abstract, no text, matching the warm-cream palette. Drop the returned URL straight into `<img src="...">`. Don't generate images for pure data artifacts (charts, tables, calculators).
- **Design system:** always load `general/design-spec` alongside this skill — it contains the five presets (colour tokens, typography, skeletons). Pick one by topic-fit; surprise when topic is aesthetic-neutral. Principles below are the floor — the spec wins on conflict.

---

## Design philosophy

The aesthetic is a deliberate hybrid of references — no single one dominates. Visual references are in `inspiration/` — the model sees them as multimodal content on turn 0 and should internalize *the feel* before emitting anything. A da Vinci influence is also present: structured curiosity, hand-annotated-notebook energy, scientific diagrams that feel handmade and exploratory even when rendered digitally.

**Universal principles (apply across every preset):**
- **One type system per artifact.** Display + workhorse + mono. Don't mix preset typography mid-document. When DESIGN_SPEC.md is loaded, the chosen preset's typography is the system — use it everywhere.
- **Lean smaller and lighter — for headings and body alike.** When the chosen preset gives explicit sizes/weights, use them. When it doesn't, default to: body 13–15 px, captions 11–12 px, sub-headings 14–18 px, the one big H1 24–34 px (not 40+); body weight 400, secondary 300, headings 400–500 (avoid 600/700 unless the preset says so). Restraint reads as confidence — whitespace + clear hierarchy do the work that bold/oversize would.
- **Sharp or near-sharp corners by default.** `border-radius: 0` to 4 px for cards. Pills (~999 px radius) only for genuine pills (badges, tags, segmented controls). Avoid the modern-SaaS "everything is 12 px rounded" look unless a preset explicitly opts into it.
- **One accent per artifact.** Pick the accent the chosen preset specifies; don't introduce a second highlight color.
- **Light mode is the default WHEN NO PRESET IS LOADED.** When DESIGN_SPEC.md is loaded, the preset decides — some are dark, some are saturated, some are cream; trust the preset.

**Cross-cutting moves:** one expressive type moment, one accent, faint gradients, generous whitespace, no decorative noise. The chosen preset (DESIGN_SPEC.md) decides palette + type + corner radius — defer to it.

**Avoid:** cold pure-white backgrounds, neon colors, hard drop-shadows for depth, rainbow gradients, the generic "neutral gray + blue primary" look, heavy bold weights as a reflex.

---

## Universal token rules

Tokens (palette, fonts, spacing) come from the chosen DESIGN_SPEC.md preset. These rules apply across every preset:

- Text: warm/neutral near-black, never `#000`. Backgrounds never pure white.
- Faint gradients only — two stops, close in lightness, same hue.
- Chart series: variations of the preset's accent + neutral greys, never a rainbow.
- Colorblind-safe: avoid red/green pairings for status; use blue/orange or accent-with-grey.
- Numeric data: `font-variant-numeric: tabular-nums` so columns align.

## Sandbox constraints
- Only `https://cdnjs.cloudflare.com` whitelisted for scripts — load all libs from there.
- Google Fonts (`fonts.googleapis.com` / `fonts.gstatic.com`) is fine for `<link>`.
- `localStorage` / `sessionStorage` are blocked — hold state in JS variables only.
- No outbound API calls — inline all data or generate it in-page.
- iframe is ~480px tall by default; design with `html, body { margin: 0; height: 100%; }`.

## Library defaults
| Need | Pick |
|---|---|
| Single chart, fast | Chart.js |
| Dashboard with sliders/filters/state | Vanilla JS + Chart.js |
| Bespoke storytelling, custom interactions | D3.js |
| 3D / WebGL | Three.js (r128 pinned on cdnjs) |

Default to **Chart.js + vanilla JS**. Reach for D3 only when the task needs custom interactions Chart.js can't deliver.

## Layout & spacing
- Generous whitespace around chart areas. 24–48px between sections, 16–24px inside cards.
- Charts breathe — never edge-to-edge with the iframe border.
- One clear hierarchy: big number / headline at top, supporting context below, controls grouped left or bottom.
- Asymmetry is fine when intentional; avoid arbitrary asymmetry.
- Use CSS Grid for dashboard layouts; Flexbox inside cards.

## Interactivity baseline
Every chart must have:
- Hover tooltips with exact values (Chart.js: tooltip enabled by default; style the body).
- Responsive sizing via `responsive: true, maintainAspectRatio: false`.
- Visible legend when 2+ series (top-aligned, same-line if width allows).
- Keyboard-focusable controls with visible focus rings.

For dashboards: sliders/filters update charts immediately — no "Apply" button. Debounce only if the recompute is expensive.

## Accessibility (non-negotiable)
- 4.5:1 contrast minimum for all text (WCAG AA).
- Visible focus rings on every interactive element (`outline: 2px solid var(--accent); outline-offset: 2px`).
- `aria-label` on icon-only buttons.
- Don't rely on color alone — pair with shape, pattern, or text.
- Icons: SVG only (Lucide is on cdnjs). Never emoji as UI icons.

## HTML hygiene (avoid the common failure modes)

These rules prevent the things that look ugly in narrow cards or long content:

- **Links are `<a>` tags. Always.** The deliverable is HTML, not markdown. `[text](url)` renders as literal text in HTML and overflows containers when URLs are long. Every link → `<a href="url">short visible text</a>`. Never paste a bare URL as visible text inside body content.
- **Visible link text stays short.** Use the source name (`Bloomberg`, `arXiv`, `TechCrunch`) — not "click here" and never the URL itself. If you need to disambiguate, append a tiny detail in parens: `<a href="...">arXiv</a> (2605.05185)`.
- **Force-break long unbreakable strings** (URLs, hashes, tokens) on text that *might* contain them: `overflow-wrap: anywhere; word-break: break-word;` on the container. Cheap insurance.
- **Cards / columns clamp their content** with `min-width: 0` on flex/grid children + `overflow: hidden` (or `clip`) on the card. Without this, one long word blows out the column width and breaks the layout.
- **No markdown anywhere in the HTML.** No `**bold**`, no `*italic*`, no `# headings`, no `[links](url)`, no fenced code blocks. Use `<strong>`, `<em>`, `<h1>...<h4>`, `<a>`, `<pre><code>`. Markdown leaks render as literal asterisks and brackets.
- **Tables wrap or scroll deliberately.** A wide `<table>` should be wrapped in `<div style="overflow-x: auto">` so it doesn't push the page wider. Better: redesign as a vertical card list at narrow widths (use `@media`).
- **Numbers use tabular figures**: `font-variant-numeric: tabular-nums` so columns of numbers align.
- **Don't include `<title>` text that the user will see.** It only sets the browser tab name in standalone view; it's invisible in the chat iframe.
- **Put the page background on `html`, not `body`** — or duplicate it on both. Otherwise the standalone "open ↗" view shows a split when content scrolls past the body box (or the body is `max-width`-centered). Pattern: `html { background: <gradient>; } body { background: transparent; }`.

## Containment
Nothing falls off the iframe. No horizontal scrollbars unless intentional. Use `min-width: 0` on flex/grid children to prevent overflow. Test that text wraps gracefully at 480px width.

## Restraint check before shipping
Before emitting the HTML, ask: *would removing this element make the design worse?* If no, remove it. Specifically look for: redundant icons next to labels, second accent colors that crept in, gradients added "for depth," shadows added "for hierarchy" that contrast already handles, animation that doesn't aid comprehension.

---

## Minimal example

This is the smallest valid artifact in the design language — copy and adapt.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Artifact</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<!-- Inter at light weights only — no 600/700 unless you have a deliberate emphatic moment.
     Fraunces optional for ONE display headline. -->
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500&family=Fraunces:opsz,wght@9..144,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    /* Light-mode default. Warm cream base, dark warm-neutral ink, single deep accent. */
    --bg: #f4f0eb; --surface: #ece6dd; --accent: #1f5a35;
    --ink: #2a2620; --muted: #6b6058; --border: rgba(42,38,32,0.08);
    --font: "Inter", system-ui, sans-serif;
    --font-serif: "Fraunces", Georgia, serif;
    --font-mono: "JetBrains Mono", ui-monospace, monospace;
  }
  html, body { margin: 0; height: 100%; }
  /* Background lives on `html` so the standalone view stays unified when content
     scrolls past the body or the body is max-width-centered. */
  html { background: linear-gradient(180deg, var(--bg) 0%, var(--surface) 100%); }
  body {
    background: transparent;
    color: var(--ink); font-family: var(--font); font-weight: 400;
    padding: 32px; box-sizing: border-box;
  }
  .eyebrow { font-family: var(--font-mono); font-weight: 400; font-size: 11px; letter-spacing: 0.04em; color: var(--accent); text-transform: lowercase; }
  h1       { font-family: var(--font-serif); font-weight: 400; font-size: 28px; line-height: 1.1; margin: 6px 0 6px; letter-spacing: -0.01em; }
  .lede    { color: var(--muted); font-weight: 300; font-size: 13px; max-width: 56ch; margin: 0 0 28px; }
  .card    { background: rgba(255,255,255,0.5); border: 1px solid var(--border); border-radius: 0; padding: 20px; }
  .chart-wrap { position: relative; height: 280px; }
  button   { background: var(--accent); color: white; border: 0; padding: 8px 14px; border-radius: 0; font: 500 12px var(--font); cursor: pointer; letter-spacing: 0.02em; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
</head>
<body>
  <div class="eyebrow">revenue / q2</div>
  <h1>Things grew the way we hoped.</h1>
  <p class="lede">A short, calm sentence framing the chart. One thought, no jargon.</p>
  <div class="card">
    <div class="chart-wrap"><canvas id="c"></canvas></div>
  </div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
  const ctx = document.getElementById('c').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['Apr','May','Jun','Jul','Aug','Sep'],
      datasets: [{
        data: [12, 19, 17, 24, 28, 31],
        borderColor: '#1f5a35',
        backgroundColor: 'rgba(31,90,53,0.08)',
        fill: true, tension: 0.35, borderWidth: 2, pointRadius: 0,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#6b6058', font: { family: 'Inter', size: 11, weight: '400' } } },
        y: { grid: { color: 'rgba(42,38,32,0.06)' }, ticks: { color: '#6b6058', font: { family: 'Inter', size: 11, weight: '400' } } }
      }
    }
  });
</script>
</body>
</html>
```

For larger boilerplate (full dashboard scaffold with sliders + multiple cards), see `assets/template.html` in this skill folder.

## When to generate images

The `generate_image(prompt, size?)` tool returns a URL like `/images/<task_id>/<n>-<slug>.png` — drop directly into `<img src="...">`. Generated images cost ~$0.05 per 1024×1024 (cheap/default/pro tier) and take 5-10 s.

**Generate one image when:**
- The artifact is article-shaped and would benefit from a hero/banner image (size `1536x1024`).
- A storytelling section needs an atmospheric visual to anchor it — abstract, mood-setting, supporting the text.
- A category card needs a small illustration that sets context (size `1024x1024`).

**Do NOT generate when:**
- The artifact is purely data (charts, dashboards, calculators) — images are visual noise here.
- The page is short / utilitarian.
- You're tempted to "fill space" — restraint reads as confidence.

**Prompt rules:**
- Subject + mood + composition + palette + style. No text/logos/people unless explicitly asked.
- Match the artifact's chosen palette: `"warm cream + faint pale-mint accents, soft morning light"`, or `"isometric forest-green geometry on dark surface"`, etc.
- Add `"no text, no logos, minimalist, editorial-style"` to keep generated images clean.

## When to delegate to a sub-agent
For substantial dashboards (3+ linked panels, multiple controls, ~10K+ chars of HTML), spawn a `worktree` sub-agent and pass it this skill's guidance plus the data. For a single chart or small page, generate inline — delegation adds latency without benefit.
