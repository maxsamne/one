> Visual and typographic system for long-form HTML articles — prose-first layout, clean serif body, optional inline SVG diagrams. Load alongside any article-writer skill.

# Article design

## Keywords
article, essay, long-form, longform, written piece, prose, editorial, thought piece, analysis, opinion, inline diagram, svg diagram, concept diagram, spider chart, radar chart, typography, article layout, reading experience

## Agent hints
- **Output:** complete self-contained HTML in a final ```html``` block. Always inline all styles — no external CSS files.
- **Preferred thinking:** `low` for layout-only; `medium` when diagrams are involved.
- **Sandbox constraints:** CSP allows only `cdnjs.cloudflare.com` for scripts; Google Fonts is fine for `<link>`.
- **Design system:** always load `general/design-spec` alongside this skill — it contains the five presets (colour tokens, typography, skeletons). Default to **Atelier Ledger** for prose articles unless content suggests another.
- **Commonly related skills:** `general/artifact-design/SKILL.md` (if you need a richer interactive section inside the article).

---

## Design philosophy

A long-form article is a reading experience, not a dashboard. The design must disappear —
the prose is the product. Every visual choice serves either legibility or comprehension,
never decoration.

One type system. One accent color. Plenty of air. That is all.

---

## Typography

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;1,400&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
```

| Role | Spec |
|---|---|
| Body | Lora 400, 17–18 px, line-height 1.8, color `var(--ink)` |
| Italic emphasis | Lora italic 400 — use sparingly for genuine emphasis |
| H1 (title) | Lora 500, 28–34 px, line-height 1.25, no letter-spacing |
| H2 (section) | Lora 400, 19–21 px, line-height 1.35, `var(--ink-muted)` |
| H3 (subsection) | Lora 400, 16 px, `var(--ink)` |
| Eyebrow / section label | JetBrains Mono 400, 11 px, uppercase, `var(--ink-muted)`, letter-spacing 0.08em |
| Caption / footnote | Lora 400, 13 px, `var(--ink-muted)` |
| Code / mono inline | JetBrains Mono 400, 14 px, `var(--surface)` background |

---

## Color tokens

```css
:root {
  --bg:         #f9f8f5;   /* warm off-white — never pure white */
  --surface:    #f0efe9;   /* slightly darker card/code background */
  --ink:        #1c1b18;   /* near-black — never pure #000 */
  --ink-muted:  #6b6860;   /* secondary text, labels, captions */
  --accent:     #2e5e4e;   /* one deep forest green — links, highlights */
  --border:     #dddbd4;   /* light separator */
}
```

One accent only. Never introduce a second color.

---

## Layout

```css
body {
  background: var(--bg);
  color: var(--ink);
  font-family: 'Lora', Georgia, serif;
  font-size: 17px;
  line-height: 1.8;
  margin: 0;
  padding: 0;
}

article {
  max-width: 700px;
  margin: 0 auto;
  padding: 48px 24px 80px;
}
```

- Max width: **700 px** — the canonical readable essay column.
- No sidebar. No two-column layout. Single column only.
- Section spacing: `margin-top: 2.5em` before each `<h2>`, `1.5em` before `<h3>`.
- Paragraph spacing: `margin-bottom: 1em` on `<p>`.
- Opening paragraph: no indent; subsequent paragraphs may use `text-indent: 1.5em` and `margin-bottom: 0` for a book-like feel on dense essays. Pick one style and hold it.

---

## Inline SVG diagrams

Use SVG for concept diagrams, framework maps, spider/radar charts, and simple relationship
diagrams. Be creative and reach for unique, aesthetically engaging forms — a well-chosen
diagram should make the reader stop, look, and understand something faster than prose could.
Prefer diagrams that are genuinely insightful over ones that are merely decorative. If the
concept is spatial, relational, or comparative, invent the visual form that best exposes it
rather than defaulting to a generic bar chart or bullet list.

**Rules:**
- Max width: 520 px, centered with `display: block; margin: 2em auto`.
- Stroke: `#1c1b18` at `stroke-width: 1.2` for primary lines; `#6b6860` at `0.8` for secondary.
- Text labels: JetBrains Mono, 11 px, `fill: #6b6860`.
- No bright colors inside diagrams. A single `var(--accent)` element is the maximum.
- Captions below diagrams: `<p class="caption">` — Lora italic 13 px, centered, `var(--ink-muted)`.
- Reach beyond radar/spider charts — consider flow diagrams, force-directed concept maps,
  annotated timelines, Sankey-style flows, or custom geometric forms if the concept calls for it.
  The diagram earns its place when it shows something prose cannot.

**Spider / radar chart skeleton:**
```html
<figure style="text-align:center;margin:2em 0">
  <svg viewBox="-120 -120 240 240" width="320" height="320"
       style="display:block;margin:0 auto;overflow:visible">
    <!-- axes -->
    <line x1="0" y1="0" x2="0"   y2="-100" stroke="#1c1b18" stroke-width="1.2"/>
    <line x1="0" y1="0" x2="95"  y2="-31"  stroke="#1c1b18" stroke-width="1.2"/>
    <line x1="0" y1="0" x2="59"  y2="81"   stroke="#1c1b18" stroke-width="1.2"/>
    <line x1="0" y1="0" x2="-59" y2="81"   stroke="#1c1b18" stroke-width="1.2"/>
    <line x1="0" y1="0" x2="-95" y2="-31"  stroke="#1c1b18" stroke-width="1.2"/>
    <!-- concentric rings -->
    <circle cx="0" cy="0" r="33"  fill="none" stroke="#dddbd4" stroke-width="0.8"/>
    <circle cx="0" cy="0" r="66"  fill="none" stroke="#dddbd4" stroke-width="0.8"/>
    <circle cx="0" cy="0" r="100" fill="none" stroke="#dddbd4" stroke-width="0.8"/>
    <!-- data polygon — replace coords with computed points -->
    <polygon points="0,-80 70,-22 40,55 -40,55 -70,-22"
             fill="#2e5e4e" fill-opacity="0.08"
             stroke="#2e5e4e" stroke-width="1.5"/>
    <!-- labels -->
    <text x="0"   y="-112" text-anchor="middle" font-family="'JetBrains Mono',monospace"
          font-size="11" fill="#6b6860">LABEL A</text>
  </svg>
  <p style="font-family:'Lora',serif;font-style:italic;font-size:13px;
             color:#6b6860;margin-top:8px">Figure 1 — caption here.</p>
</figure>
```

---

## Footnotes

Place footnotes as numbered superscripts inline (`<sup><a href="#fn1">1</a></sup>`) and
collect them at the bottom inside a `<section class="footnotes">` with a light top border.

```html
<section class="footnotes" style="border-top:1px solid var(--border);
  margin-top:3em;padding-top:1.5em">
  <ol style="font-family:'Lora',serif;font-size:13px;color:var(--ink-muted);
              line-height:1.7;padding-left:1.5em">
    <li id="fn1">Footnote text here. <a href="#ref1" style="color:var(--accent)">↩</a></li>
  </ol>
</section>
```

---

## Links

All links: `color: var(--accent)`, no underline by default, underline on hover.

```css
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
```

---

## Minimal page skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;1,400&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#f9f8f5; --surface:#f0efe9; --ink:#1c1b18;
  --ink-muted:#6b6860; --accent:#2e5e4e; --border:#dddbd4;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--bg);color:var(--ink);
  font-family:'Lora',Georgia,serif;font-size:17px;line-height:1.8}
article{max-width:700px;margin:0 auto;padding:48px 24px 80px}
h1{font-size:30px;font-weight:500;line-height:1.25;margin-bottom:.5em}
h2{font-size:20px;font-weight:400;line-height:1.35;margin:2.5em 0 .75em;color:var(--ink)}
h3{font-size:16px;margin:1.5em 0 .5em}
p{margin-bottom:1em}
.eyebrow{font-family:'JetBrains Mono',monospace;font-size:11px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--ink-muted);margin-bottom:.5em}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head>
<body>
<article>
  <p class="eyebrow">Domain · Month Year</p>
  <h1>Article Title</h1>
  <p>Opening paragraph…</p>

  <h2>1. Section heading</h2>
  <p>Body text…</p>
</article>
</body>
</html>
```

---

## What NOT to do

- Don't use pure white (`#fff`) background or pure black (`#000`) text.
- Don't use sans-serif for body text — this system is serif-first.
- Don't add a sidebar, multi-column layout, or navigation bar.
- Don't use bold (`font-weight: 600+`) for anything except rare emphasis; Lora 400 carries the text.
- Don't add drop shadows, gradients on cards, or rounded boxes — this isn't a dashboard.
- Don't introduce a second accent color. The `--accent` token is singular.
- Don't size the H1 above 36 px — this is prose, not a landing page hero.
- Don't put diagrams in every section. A diagram earns its place only when the concept is genuinely spatial or relational.
