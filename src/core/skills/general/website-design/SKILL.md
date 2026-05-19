> Personal website skill — builds and updates pages in `docs/` for static GitHub Pages hosting. Pairs with the shared DESIGN_SPEC.md. **When reference images are attached, take heavy inspiration from them — composition, density, palette, type voice, imagery — and pick the design-spec preset that matches the reference's mood.**

# Website design

## Keywords
website, personal site, homepage, landing page, about page, writing page, blog, portfolio, github pages, personal page, site

## Agent hints
- **Output:** write complete self-contained HTML files to `docs/`. Always inline all styles — no external CSS files, no build step.
- **Design system:** always load `general/design-spec` alongside this skill — it contains the five presets (colour tokens, typography, skeletons, imagery guidance).
- **Reference images come first.** If the user attached reference screenshots, they are the primary brief. Echo the reference's composition (hero / grid / chapter cards / whatever is there), density, palette family, and type voice. Pick the design-spec preset that best matches the reference's mood and translate the reference *through* that preset. Do not default to a sparser layout than the reference shows.
- **No references? Default to Atelier Ledger.** Warm parchment tones, humanist serif for headings, generous whitespace. Switch presets if the page content calls for a different mood (a product-adjacent page → Porcelain Ops, a manifesto page → Monument Press, etc.).
- **After writing files:** `git add docs/`, `git commit`, `git push` — GitHub Pages auto-deploys on push.
- **Preferred thinking:** `low` for copy-only updates; `medium` for new page layouts or reference-driven redesigns.
- **Images:** you may generate up to 5 images per task using the `generate_image` tool when the reference or the page calls for them (hero diagrams, chapter cards, portrait, ambient illustrations). Save them to `docs/images/` and reference with a root-relative path (e.g. `/one/images/filename.png`). Don't generate speculatively — but don't skip a clearly called-for hero image just to stay sparse.
- **Commonly related skills:** `general/artifact-design/SKILL.md` (for the full DESIGN_SPEC), `general/article-design/SKILL.md` (for writing/essay pages).

---

## Site structure

```
docs/
  index.html       # homepage
  writing/
    index.html     # writing index
    <slug>.html    # individual articles
  work/
    index.html     # work / portfolio index
  design.html      # living style guide (the DESIGN_SPEC rendered as a page)
```

All internal links use root-relative paths prefixed with `/one/` (GitHub Pages project repo base path). When a custom domain is connected, update base path to `/`.

---

## Page anatomy

Every page shares the same nav and footer. Copy this shell exactly — don't invent new nav patterns:

```html
<nav>
  <a class="wordmark" href="/one/">MS</a>
  <ul>
    <li><a href="/one/writing">Writing</a></li>
    <li><a href="/one/work">Work</a></li>
  </ul>
</nav>
```

---

## Design principles (site-specific)

These extend the DESIGN_SPEC — they don't override it:

- **Reference-driven preset selection.** When a reference is attached, the reference picks the preset, not a hardcoded default. Match its visual density, hero style, and use of imagery.
- **No-reference default: Atelier Ledger.** Warm parchment tones, humanist serif for headings, generous whitespace.
- **Inspiration ≠ imitation.** Reference images are examples of a *design language*, not templates to copy. Take cues from: colour palette, fonts/typography, kinds of imagery, image style, object/element vocabulary, corner-radius character, density. Do **not** copy specific images, headlines, hero compositions, or section layouts 1:1 — the site must keep its own brand identity. Add your own creative twist on top of the borrowed language.
- **Writing pages:** prose-first. Lora body, generous line-height (1.75+), max-width ~680px.
- **No JavaScript by default.** Add it only when interactivity is genuinely needed.
- **No framework, no build.** Plain HTML + inlined CSS. GitHub Pages serves it directly.
- **No non-functional interactive elements.** Never build UI that *implies* a working backend it doesn't have — chat inputs, search bars, login forms, "subscribe" inputs, send buttons, comment boxes, like/upvote controls, or anything else a visitor would reasonably expect to *do something* when used. If the backend doesn't exist, the element doesn't exist. Cosmetic-only things are fine (tabs that navigate between static pages, image carousels, animated decorations, theme toggles, badges, status pills that just label state) — the test is: *would a reasonable visitor type/click this and expect a response?* If yes and there's no handler, cut it.

---

## GitHub Pages constraints

- Static files only — no server-side logic.
- Base URL: `https://maxsamne.github.io/one/` until a custom domain is set.
- Custom domain: create `docs/CNAME` containing just the bare domain (e.g. `maxsamne.com`). GitHub Pages picks it up automatically.
- All asset paths must be relative or use the `/one/` prefix.
