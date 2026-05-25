> Daily morning briefing — distilled rundown of whatever the user asks to be briefed on. Pulled in for any "morning brief", "daily briefing", "what's happening today" style task. Output is always an HTML artifact.

# Morning brief

## Keywords
morning brief, morning briefing, daily brief, daily briefing, brief, briefing, news roundup, today's roundup, today's news, what's happening, weekly recap, week ahead, monday brief

## Agent hints
- **Output:** complete self-contained HTML emitted **inline** as a final ```html``` code block in your response — never via `write_file`. The gateway renders from the response block, not from files on disk. If you only write to a file, the user sees nothing.
- **Token budget:** if the full HTML would exceed ~6000 tokens, trim sections (fewer entries per section, shorter lede) rather than writing to file. A trimmed brief is better than a broken one.
- **Preferred thinking:** `medium` (multiple web searches, synthesis, structured layout).
- **Always also load:** `general/artifact-design/SKILL.md` if not already attached. Use its design language (warm-cream light mode, Inter at 300/400/500, Fraunces for the one display headline, JetBrains Mono for eyebrows + tags).

## How to read the request

The user's prompt names the *topic* (e.g. "morning brief on AI research", "weekly brief on European VC", "what's happening in climate tech today"). Treat the topic as the brief's scope — don't add unrelated sections, don't pad with weather or markets unless explicitly asked.

If the request is generic ("morning brief", no topic), pick 2–4 sections that fit the user's apparent context and ship — don't ask clarifying questions.

## What to produce

A single HTML page. Tone: **distilled, plain language, confident, specific**. No marketing fluff. No "in this rapidly evolving landscape". Just the facts that matter, with concrete numbers / names / dates.

Structure (adapt section count + naming to the topic):

1. **Hero** — `<topic> · <weekday> <date>` mono caption (use today's date from the system prompt) + serif H1 with one calm framing sentence (e.g. *"Wednesday — three rounds, two announcements, one quiet macro."*). Below: a one-line lede summarising the most important thing from the last 36 hours.
   - **Generate one hero image.** Call `generate_image(prompt, size="1536x1024")` with a prompt that captures the day's *mood* — atmospheric, abstract or scenic, highly textured, rich, and avoiding flat or sterile digital vector looks.

  - **Pick a design flavor (to switch things up).** Choose one of the following rich visual themes based on the brief's topic (or randomly if it’s generic):
    - **Silicon Sociology flavor (Retro Pixel-Art):** A nostalgic, highly detailed retro 16-bit or 32-bit pixel-art aesthetic capturing an evocative, quiet scene at dawn or dusk. For example, a city skyline (like Stockholm) across a body of water, viewed from a peaceful grassy hill dotted with wildflowers, with an open laptop showing code and a closed leather notebook on the grass. Warm golden hour light with soft peach, pale gold, and blue sky. Deeply atmospheric, blending vintage tech with nature.
    - **Yesterday Test flavor (Archival Technical Painting):** An atmospheric, textured classical painting or rich oil-on-canvas style. It depicts an early historical technology test (e.g., a vintage rocket prototype or experimental machine) on a rustic wooden scaffolding at dawn. Heavy warm golden lighting, aged paper/canvas texture, dusty atmosphere, and delicate technical blueprints, engineering schematics, or hand-drawn ink notes faintly overlaid across the sky.
    - **Textured Abstract/Artisanal flavor:** Moving beyond flat digital vectors, this style uses rich painterly brushstrokes, mixed-media paper collages, raw charcoal sketches, or weathered blueprint textures with a single warm accent color (like deep forest green or burnt orange) against a textured off-white/cream paper canvas. High tactile feel, moody and thoughtful.

  - Then write a highly specific, concrete `generate_image` prompt based on that flavor. Examples:
    - Silicon Sociology flavor: `"detailed 16-bit pixel art of Stockholm city skyline across water at sunrise, viewed from a grassy hill with wildflowers, an open laptop showing lines of code on the grass, a closed green notebook next to it, warm golden hour peach and soft blue sky, nostalgic, vintage editorial-illustration, highly detailed, atmospheric"`
    - Yesterday Test flavor: `"oil painting style, an early vintage rocket prototype on a rustic wooden scaffold at dawn, warm golden sunrise light, dusty air, faint technical blueprint lines and architectural drawings overlaid in the sky, aged paper texture, fine canvas weave visible, historical scientific journal aesthetic, masterpiece"`
    - Textured Abstract/Artisanal flavor: `"textured mixed-media painting, abstract composition of charcoal lines and a single block of textured forest green pigment on heavily aged, weathered cream paper, rough tactile brushstrokes, no flat vector shapes, minimalist and moody, editorial-style"`
   - Drop the returned URL straight into the hero card: `<img src="<returned URL>" alt="" style="width:100%;height:220px;object-fit:cover;border-radius:14px;">`.
   - **One hero image only, and up to 2 extra supporting images (optional).** The supporting images are genuinely optional — skip them entirely unless they earn their place. When you do include them, they must be *relevant* to the brief's content and *consistent* with its aesthetic (same warm-cream + single-accent palette, same atmospheric/abstract mood, no text/logos/people). Each supporting image should either anchor a specific section it sits next to (then it should reflect that section's subject) or set a general mood that complements the overall piece. Never generate per-section images mechanically — the brief is meant to be scanned, not browsed.

2. **Body sections** — 2–5 sections derived from the topic. Each section: short mono eyebrow label, a list of one-line entries with concrete specifics. Format each entry as: `**Subject** — one-line what happened — source.` Skip "exciting", "innovative", etc. Be a wire service.

3. **Footer** (optional, mono, small) — a one-line "what to watch next" hook. Keep it sparse.

## Sourcing

Use `web_search` aggressively. Build queries from the topic + today's date. Always prefer named outlets/primary sources over aggregators.

**Date filter — strictly enforced.** The system prompt contains today's date. Only include stories published **today or yesterday** (i.e. within the last ~36 hours). If you cannot confirm a story's publication date is within that window, omit it entirely. Do not include events from earlier in the week or "this month" — the brief is a *daily* snapshot, not a weekly digest. Include the publication date next to each entry's source link so the user can verify recency at a glance (e.g. `<a href="...">Bloomberg · May 14</a>`).

**Citations: ALWAYS HTML, NEVER MARKDOWN.** The deliverable is an HTML artifact — markdown syntax like `[Outlet](url)` renders as literal text and overflows narrow cards. Every link must be a real `<a>` tag with concise visible text:

✅ `<a href="https://example.com/article">Bloomberg</a>`
❌ `[Bloomberg](https://example.com/article)` ← never inside HTML
❌ Bare URLs as visible text — overflow risk and visual noise.

## What NOT to do

- Don't ask the user clarifying questions. Make reasonable inferences and ship.
- Don't include placeholders ("XX million", "TBD"). If you can't find a real number, leave the entry out.
- Don't include stories older than 36 hours. If today + yesterday yield too few results, shrink the brief — don't pad with older news.
- Don't restate every section's purpose. Headers are enough; jump straight to content.
- Don't bold every other word. Bold subjects (company / paper / person) and key numbers only.
- Don't use emoji as section markers. Use mono labels or single-glyph dots if you want hierarchy.
- Don't include a "disclaimer" footer.
- Don't make the artifact taller than ~1200 px without a reason — the user reads it in a panel, not a full page.
- Don't return prose instead of HTML. The output is always a ```html``` block.
