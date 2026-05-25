---
suggested_for_skills:
  - general/website-design/SKILL.md
---

> Grades website changes for layout integrity, design alignment, aesthetic distinctiveness, and security hygiene.

## Criteria

### layout_integrity (weight: 2)
Does every element render without overflow, clipping, or breakage? Check:
- SVG diagrams: text fits inside its bounding box; no labels overlap or spill outside strokes.
- Boxes and containers: content does not exceed declared width or height.
- Navigation and footer: no wrapping or collapsing on a standard viewport (~1200px wide).
- Images and media: constrained with `max-width: 100%`; nothing bleeds past the article column.
- Long strings (URLs, code, labels): break or truncate rather than forcing horizontal scroll.
Cite the specific element and symptom for any failure. A single confirmed overflow should block acceptance until fixed.

### design_alignment (weight: 2)
Does the output faithfully follow the design system defined in the website-design skill and the DESIGN_SPEC?
- Correct colour tokens (`--bg`, `--ink`, `--accent`, etc.) — no hardcoded hex values that deviate from the palette.
- Typography: Lora for headings and body prose, Inter for UI elements, JetBrains Mono for labels and code. No other typefaces introduced.
- Spacing: generous whitespace; consistent padding rhythm matching existing pages.
- No external CSS frameworks, no build step, no JavaScript unless strictly necessary.
- Internal links use the `/one/` base path prefix.
Penalise any deviation from the above, even if the result looks "fine" — consistency is load-bearing for a personal site.

### aesthetic_distinctiveness (weight: 1)
Does the page feel intentional and visually confident, or does it look like a template?
An optimal result has at least one moment of considered craft (a typographic choice, a restrained use of the accent colour, a layout decision that wouldn't appear by default). Block only when the result feels generic, interchangeable, or like any bland personal site. Do not penalise restraint — sparse and deliberate is better than decorated and generic.

### functional_integrity (weight: 2)
Does every interactive element on the page actually do something?
The site is static HTML on GitHub Pages — there is no backend. So any element that *implies* server interaction must either be wired to a real frontend behaviour (anchor link, page navigation, JS toggle of visible state) or it must not exist at all. Specifically check for:
- Chat inputs or "ask me anything" boxes with no JS handler and no submission target.
- Search bars that don't filter or navigate.
- Login / signup / subscribe forms with no `action` or no JS.
- Comment boxes, like buttons, upvote controls, or any reaction UI.
- "Send" / "submit" buttons whose only behaviour is hover styling.
- Inputs that visually resemble live fields but have no handler.
Cosmetic-only UI is fine: tabs that navigate between real pages, image carousels, theme toggles, animated decorations, badges, status pills used as labels. The test is: *would a reasonable visitor type or click this and expect a response?* If yes and nothing happens, cite the offending element and block acceptance. A single non-functional interactive element is enough to fail this criterion.

### security_hygiene (weight: 2)
Does the committed HTML contain anything that should not be public?
Check for:
- API keys, tokens, secrets, or credentials in any form (inline, commented out, in data attributes).
- Internal company names, fund names, portfolio company names, or proprietary business logic not intended for public disclosure.
- Personal data (email addresses, phone numbers, private identifiers) beyond what the owner has chosen to display.
- Hardcoded internal URLs, staging endpoints, or environment-specific configuration.
A single confirmed leak must block the PR.
