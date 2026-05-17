> Global design system — five visual presets with colour tokens, typography, signature components, and HTML skeletons. Load this alongside any design skill (artifact-design, article-design, website-design) or on its own when the task is purely about visual identity or theming.

# Design spec

## Keywords
design, theme, palette, typography, preset, colour, color, tokens, visual identity, brand, style guide, design system, fonts, spacing, components, neon foundry, porcelain ops, atelier ledger, signal glyph, monument press

---

## Preset menu
| Preset | Vibe | When to use |
|---|---|---|
| **1. Neon Foundry** | dark compute-lab, prism glow, terminal-grade precision | devtools, AI infra, auth, API docs |
| **2. Porcelain Ops** | airy off-white product UI, quiet confidence, near-invisible chrome | SaaS landing pages, analytics, onboarding |
| **3. Atelier Ledger** | renaissance notebook, parchment engineering, humanist scholarship | research essays, invention explainers, archival storytelling |
| **4. Signal Glyph** | consumer-tech minimalism, dot-matrix cues, hardware UI clarity | mobile concepts, device launches, feature demos |
| **5. Monument Press** | manifesto-scale editorial, bold black type, blueprint accents | vision pages, careers, fund narratives, "AI era" statements |

### Preset 1 — Neon Foundry
**Vibe (1–2 sentences)** — Midnight infra dashboard meets terminal brutalism and luminous isometric compute. Sharp, dark, exact; small amounts of iridescence feel expensive, not playful.

**When to use it** — Developer platform homepages, sign-in/auth flows, API or CLI onboarding.

**Typography** — `@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=Manrope:wght@400;500;700&family=Rajdhani:wght@500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap');`  
Display headline: Sora 700; Section heading: Rajdhani 700; Body: Manrope 400/500; Caption: IBM Plex Sans 400; Eyebrow label: Rajdhani 500 uppercase; Mono tag: IBM Plex Mono 500.

**Colour tokens**
```css
:root{
  --bg:#070808;--surface:#111515;--ink:#f5f7f6;--ink-muted:#9aa39e;
  --accent:#66f08b;--border:#2a3130;--tag-bg:#111c16;
}
```

**Layout & spacing** — max-width: 1120px; page padding: 32px; card padding: 24px; gap: 24px.

**Signature components (2–3)** —  
Auth pill: full-width outlined button with faint inner glow.  
```html
<button class="nf-pill">Continue with GitHub</button>
<style>.nf-pill{width:100%;padding:14px 18px;border:1px solid var(--border);border-radius:999px;background:#090a0a;color:var(--ink);box-shadow:inset 0 0 0 1px #ffffff08}</style>
```  
Code slab: tilted dark panel with low-contrast border and mono code.  
```html
<pre class="nf-slab">npm i @agent/core</pre>
<style>.nf-slab{padding:18px;border:1px solid var(--border);border-radius:18px;background:linear-gradient(180deg,#151919,#0e1111);font:500 13px/1.6 "IBM Plex Mono",monospace;color:#b7c8bf}</style>
```  
Status tag: tiny mono badge with acid-green dot.  
```html
<span class="nf-tag">● LIVE</span>
<style>.nf-tag{display:inline-flex;gap:8px;padding:6px 10px;border:1px solid var(--border);border-radius:999px;background:var(--tag-bg);font:500 12px "IBM Plex Mono",monospace;color:var(--accent)}</style>
```

**Skeleton**
```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=Manrope:wght@400;500;700&family=Rajdhani:wght@500;700&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap');:root{--bg:#070808;--surface:#111515;--ink:#f5f7f6;--ink-muted:#9aa39e;--accent:#66f08b;--border:#2a3130;--tag-bg:#111c16}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.6 Manrope,sans-serif}main{max-width:1120px;margin:auto;padding:32px;display:grid;gap:24px}.card{background:var(--surface);border:1px solid var(--border);border-radius:24px;padding:24px}h1{margin:0;font:700 clamp(40px,8vw,84px)/.96 Sora,sans-serif}h2{margin:0 0 8px;font:700 18px Rajdhani,sans-serif;letter-spacing:.08em;text-transform:uppercase}p{margin:0;color:var(--ink-muted)}.row{display:grid;grid-template-columns:1.2fr .8fr;gap:24px}.btn{display:inline-block;padding:14px 18px;border:1px solid var(--border);border-radius:999px;color:var(--ink);text-decoration:none}.mono{font-family:"IBM Plex Mono",monospace;color:var(--accent)}</style></head>
<body><main><section class="row"><div class="card"><div class="mono">DEPLOY / 04</div><h1>Run agents where the code already lives.</h1><p>Auth, jobs, logs, and CLI onboarding in one dark surface.</p></div><aside class="card"><h2>Quickstart</h2><pre class="mono">npx agent init</pre><a class="btn" href="#">Continue with GitHub</a></aside></section><section class="card"><h2>Recent events</h2><p>Build passed • 12s ago</p></section></main></body></html>
```

### Preset 2 — Porcelain Ops
**Vibe (1–2 sentences)** — Soft enterprise minimalism: warm-white canvas, hairline borders, low-saturation charts, generous air. It feels like a product team that sweats details and never shouts.

**When to use it** — Analytics explainers, AI agent orchestration pages, onboarding guides, chapter-style resources.

**Typography** — `@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=Source+Sans+3:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');`  
Display headline: Hanken Grotesk 600; Section heading: Hanken Grotesk 500; Body: Source Sans 3 400; Caption: Source Sans 3 400; Eyebrow label: DM Mono 500; Mono tag: DM Mono 400.

**Colour tokens**
```css
:root{
  --bg:#f7f5ef;--surface:#fffdf8;--ink:#262521;--ink-muted:#7d786f;
  --accent:#7fb89d;--border:#e7e1d6;--tag-bg:#f2eee5;
}
```

**Layout & spacing** — max-width: 1200px; page padding: 40px; card padding: 28px; gap: 28px.

**Signature components (2–3)** —  
Metric strip: quiet stat + thin progress ruler.  
```html
<div class="po-metric"><strong>49,182</strong><i></i></div>
<style>.po-metric strong{display:block;font:600 34px/1 "Hanken Grotesk",sans-serif}.po-metric i{display:block;height:6px;margin-top:10px;border-radius:999px;background:linear-gradient(90deg,#8bc3a7,#d8c65f,#ef9c76)}</style>
```  
Soft board: floating panel with almost invisible shadow.  
```html
<div class="po-board">Live users</div>
<style>.po-board{padding:28px;border:1px solid var(--border);border-radius:20px;background:var(--surface);box-shadow:0 12px 32px #00000008}</style>
```  
Chapter card: tall learning tile with subdued divider.  
```html
<article class="po-chapter"><small>Chapter II</small><h3>How To Build</h3></article>
<style>.po-chapter{padding:28px;border:1px solid var(--border);border-radius:24px;background:var(--surface)}.po-chapter h3{margin:10px 0 0;font:600 32px/1.05 "Hanken Grotesk",sans-serif}</style>
```

**Skeleton**
```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>@import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&family=Source+Sans+3:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');:root{--bg:#f7f5ef;--surface:#fffdf8;--ink:#262521;--ink-muted:#7d786f;--accent:#7fb89d;--border:#e7e1d6;--tag-bg:#f2eee5}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:400 17px/1.6 "Source Sans 3",sans-serif}main{max-width:1200px;margin:auto;padding:40px;display:grid;gap:28px}.hero{display:grid;grid-template-columns:.9fr 1.1fr;gap:28px;align-items:center}.card{background:var(--surface);border:1px solid var(--border);border-radius:24px;padding:28px;box-shadow:0 12px 32px #00000008}h1{margin:0 0 14px;font:600 clamp(42px,6vw,72px)/1 "Hanken Grotesk",sans-serif}h2{margin:0;font:500 24px/1.1 "Hanken Grotesk",sans-serif}p{margin:0;color:var(--ink-muted)}.eyebrow{font:500 12px "DM Mono",monospace;text-transform:uppercase}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}</style></head>
<body><main><section class="hero"><div><div class="eyebrow">OPS / GUIDE</div><h1>Scale with product analytics, payments, and support.</h1><p>Calm surfaces, strong hierarchy, understated trust.</p></div><div class="card"><h2>Monthly active users</h2><p>49,182 • +37%</p></div></section><section class="grid"><article class="card"><div class="eyebrow">Chapter I</div><h2>How To Start</h2></article><article class="card"><div class="eyebrow">Chapter II</div><h2>How To Build</h2></article><article class="card"><div class="eyebrow">Chapter III</div><h2>How To Scale</h2></article></section></main></body></html>
```

### Preset 3 — Atelier Ledger
**Vibe (1–2 sentences)** — Leonardo notebook, museum label, field journal. Warm paper, sepia ink, annotated elegance; it should feel thoughtful, tactile, and a little obsessive.

**When to use it** — Historical or scientific essays, invention timelines, lab notebooks, concept dossiers.

**Typography** — `@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Cardo:wght@400;700&family=Alegreya+SC:wght@400;700&family=EB+Garamond:ital,wght@0,400;1,400&family=Cutive+Mono&display=swap');`  
Display headline: Cormorant Garamond 600; Section heading: Alegreya SC 700; Body: Cardo 400; Caption: EB Garamond Italic 400; Eyebrow label: Alegreya SC 400; Mono tag: Cutive Mono 400.

**Colour tokens**
```css
:root{
  --bg:#efe2c6;--surface:#f6ecd7;--ink:#5d3823;--ink-muted:#8f6f56;
  --accent:#a46738;--border:#d3bc98;--tag-bg:#ead8b8;
}
```

**Layout & spacing** — max-width: 980px; page padding: 36px; card padding: 22px; gap: 22px.

**Signature components (2–3)** —  
Margin note: narrow annotation bar for side comments.  
```html
<aside class="al-note">Fig. 3 — water lift</aside>
<style>.al-note{padding-left:14px;border-left:2px solid var(--accent);font:400 15px/1.5 "EB Garamond",serif;font-style:italic;color:var(--ink-muted)}</style>
```  
Ruled folio: paper card with faint drafting lines.  
```html
<div class="al-folio">Mechanism sketch</div>
<style>.al-folio{padding:22px;border:1px solid var(--border);border-radius:14px;background:repeating-linear-gradient(180deg,var(--surface),var(--surface) 31px,#0000 31px,#0000 32px),var(--surface)}</style>
```  
Spec tag: typewritten archival label.  
```html
<span class="al-tag">CATALOG / 1502</span>
<style>.al-tag{padding:6px 10px;background:var(--tag-bg);border:1px solid var(--border);font:400 12px "Cutive Mono",monospace;color:var(--ink)}</style>
```

**Skeleton**
```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Cardo:wght@400;700&family=Alegreya+SC:wght@400;700&family=EB+Garamond:ital,wght@0,400;1,400&family=Cutive+Mono&display=swap');:root{--bg:#efe2c6;--surface:#f6ecd7;--ink:#5d3823;--ink-muted:#8f6f56;--accent:#a46738;--border:#d3bc98;--tag-bg:#ead8b8}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:400 19px/1.7 Cardo,serif}main{max-width:980px;margin:auto;padding:36px;display:grid;gap:22px}.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:22px}h1{margin:0;font:600 clamp(48px,8vw,88px)/.95 "Cormorant Garamond",serif}h2{margin:0 0 8px;font:700 20px "Alegreya SC",serif;letter-spacing:.03em}p{margin:0;color:var(--ink-muted)}.eyebrow,.mono{font-family:"Cutive Mono",monospace;font-size:12px}</style></head>
<body><main><div class="eyebrow">FOLIO / XII</div><h1>The machine begins as a sketch in the margin.</h1><section class="card"><h2>Observation</h2><p>Use warm paper, restrained ornament, and annotation-like captions.</p></section><aside class="card"><em style="font-family:'EB Garamond',serif">Fig. 1 — wheel, rope, incline.</em></aside></main></body></html>
```

### Preset 4 — Signal Glyph
**Vibe (1–2 sentences)** — Nothing-style interface language: dot-matrix cues, monochrome hardware calm, precise radii, one "signal" color. Feels like industrial design documentation translated into UI.

**When to use it** — Phone or wearable launches, mobile app concepts, feature callouts, experimental consumer tech.

**Typography** — `@import url('https://fonts.googleapis.com/css2?family=DotGothic16&family=Syne:wght@500;700;800&family=Archivo:wght@400;500;700&family=Share+Tech+Mono&display=swap');`  
Display headline: Syne 700; Section heading: Archivo 700; Body: Archivo 400; Caption: Archivo 400; Eyebrow label: DotGothic16; Mono tag: Share Tech Mono.

**Colour tokens**
```css
:root{
  --bg:#ece9e5;--surface:#f8f6f3;--ink:#161616;--ink-muted:#676767;
  --accent:#db3a34;--border:#d2cdc7;--tag-bg:#e3dfda;
}
```

**Layout & spacing** — max-width: 1160px; page padding: 28px; card padding: 24px; gap: 20px.

**Signature components (2–3)** —  
Dot label: microcopy in matrix styling.  
```html
<div class="sg-dot">STATUS BAR</div>
<style>.sg-dot{font:400 14px/1 "DotGothic16",sans-serif;letter-spacing:.04em}</style>
```  
Capsule toggle: thick, hardware-like segmented switch.  
```html
<div class="sg-toggle"><b>Day</b><span>Week</span></div>
<style>.sg-toggle{display:inline-flex;padding:4px;background:var(--tag-bg);border-radius:999px}.sg-toggle>*{padding:8px 20px;border-radius:999px}.sg-toggle b{background:#6c6c6c;color:#fff}</style>
```  
Exploded card: rounded panel for a phone crop or module callout.  
```html
<div class="sg-panel">App icons for essential notifications only</div>
<style>.sg-panel{padding:24px;border:1px solid var(--border);border-radius:28px;background:#ddd8d5;color:var(--ink)}</style>
```

**Skeleton**
```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>@import url('https://fonts.googleapis.com/css2?family=DotGothic16&family=Syne:wght@500;700;800&family=Archivo:wght@400;500;700&family=Share+Tech+Mono&display=swap');:root{--bg:#ece9e5;--surface:#f8f6f3;--ink:#161616;--ink-muted:#676767;--accent:#db3a34;--border:#d2cdc7;--tag-bg:#e3dfda}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.6 Archivo,sans-serif}main{max-width:1160px;margin:auto;padding:28px;display:grid;gap:20px}.hero{display:grid;grid-template-columns:1fr 1fr;gap:20px}.card{background:var(--surface);border:1px solid var(--border);border-radius:28px;padding:24px}h1{margin:0;font:700 clamp(38px,6vw,68px)/1 Syne,sans-serif}h2{margin:0 0 8px;font:700 20px Archivo,sans-serif}.dot{font:400 13px "DotGothic16",sans-serif}.muted{color:var(--ink-muted)}</style></head>
<body><main><div class="dot">PHONE / 03A</div><section class="hero"><div class="card"><h1>Essential notifications only.</h1><p class="muted">Matrix labels, blunt pills, almost-no palette.</p></div><div class="card"><h2>AI usage</h2><div style="display:inline-flex;padding:4px;background:var(--tag-bg);border-radius:999px"><span style="background:#6c6c6c;color:#fff;padding:8px 20px;border-radius:999px">Day</span><span style="padding:8px 20px">Week</span></div></div></section></main></body></html>
```

### Preset 5 — Monument Press
**Vibe (1–2 sentences)** — Editorial broadside with startup ambition: giant black headlines, white space, blueprint-blue line accents, and occasional romantic serif relief. Think modernist careers page, cultural institution, and future-facing manifesto.

**When to use it** — Brand manifestos, hiring pages, "rethinking X" narratives, founder letters, vision decks.

**Typography** — `@import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@600;700;800&family=Bodoni+Moda:opsz,wght@6..96,500;6..96,700&family=Source+Serif+4:wght@400;600&family=Roboto+Mono:wght@400;500&display=swap');`  
Display headline: League Spartan 800; Section heading: Bodoni Moda 700; Body: Source Serif 4 400; Caption: Roboto Mono 400; Eyebrow label: Roboto Mono 500 uppercase; Mono tag: Roboto Mono 400.

**Colour tokens**
```css
:root{
  --bg:#fcfbf8;--surface:#ffffff;--ink:#0d0d0f;--ink-muted:#5e5b57;
  --accent:#5867ff;--border:#e6e2da;--tag-bg:#f3f2ef;
}
```

**Layout & spacing** — max-width: 1280px; page padding: 32px; card padding: 26px; gap: 26px.

**Signature components (2–3)** —  
Split manifesto hero: oversized headline divided across columns.  
```html
<section class="mp-hero"><h1>RETHINKING MONEY</h1><h1>FOR THE AI ERA</h1></section>
<style>.mp-hero{display:grid;grid-template-columns:1fr 1fr;gap:26px}.mp-hero h1{margin:0;font:800 clamp(54px,9vw,120px)/.88 "League Spartan",sans-serif}</style>
```  
Blueprint panel: white card with thin blue diagram lines.  
```html
<div class="mp-blueprint"></div>
<style>.mp-blueprint{height:220px;border:1px solid var(--border);border-radius:22px;background:
linear-gradient(var(--surface),var(--surface)),
repeating-linear-gradient(90deg,#5867ff22 0 1px,#0000 1px 40px),
repeating-linear-gradient(#5867ff22 0 1px,#0000 1px 40px)}</style>
```  
Editorial CTA: severe dark button on pale field.  
```html
<a class="mp-cta" href="#">Open positions →</a>
<style>.mp-cta{display:inline-block;padding:14px 18px;background:var(--ink);color:#fff;text-decoration:none;border-radius:12px;font:500 13px "Roboto Mono",monospace}</style>
```

**Skeleton**
```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>@import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@600;700;800&family=Bodoni+Moda:opsz,wght@6..96,500;6..96,700&family=Source+Serif+4:wght@400;600&family=Roboto+Mono:wght@400;500&display=swap');:root{--bg:#fcfbf8;--surface:#ffffff;--ink:#0d0d0f;--ink-muted:#5e5b57;--accent:#5867ff;--border:#e6e2da;--tag-bg:#f3f2ef}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:400 18px/1.6 "Source Serif 4",serif}main{max-width:1280px;margin:auto;padding:32px;display:grid;gap:26px}.hero{display:grid;grid-template-columns:1fr 1fr;gap:26px;align-items:start}.card{background:var(--surface);border:1px solid var(--border);border-radius:22px;padding:26px}h1{margin:0;font:800 clamp(54px,9vw,118px)/.88 "League Spartan",sans-serif}h2{margin:0 0 8px;font:700 28px/1 "Bodoni Moda",serif}.eyebrow{font:500 12px "Roboto Mono",monospace;text-transform:uppercase}.btn{display:inline-block;padding:14px 18px;border-radius:12px;background:var(--ink);color:#fff;text-decoration:none;font:500 13px "Roboto Mono",monospace}</style></head>
<body><main><div class="eyebrow">CAREERS AT AUGUST</div><section class="hero"><h1>RETHINKING MONEY</h1><div><h1>FOR THE AI ERA</h1><p style="color:var(--ink-muted)">Use blueprint accents sparingly; let the typography do the work.</p><a class="btn" href="#">Open positions →</a></div></section><section class="card"><h2>Build forever.</h2><p>Manifesto-scale layouts, sharp contrast, disciplined restraint.</p></section></main></body></html>
```

## Cross-preset principles
- Start with one preset; do not mix type systems, radii, or palettes across presets.
- Generous whitespace beats decorative fill.
- Keep visible hierarchy obvious within 3 seconds: eyebrow → headline → support → action.
- Use color accents sparingly; one accent should carry the page.
- Borders stay hairline and purposeful; shadows stay soft and rare.
- Images/illustrations should match the preset's emotional temperature.
- Focus rings must be obvious and high-contrast.
- Maintain accessible contrast for all text and controls.
- Motion, if any, should clarify state, never decorate.
- Default to restraint: fewer components, stronger composition.
