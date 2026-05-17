> Personal website skill — builds and updates pages in `docs/` following the shared DESIGN_SPEC.md design system. For static HTML pages deployed via GitHub Pages.

# Website design

## Keywords
website, personal site, homepage, landing page, about page, writing page, blog, portfolio, github pages, personal page, site

## Agent hints
- **Output:** write complete self-contained HTML files to `docs/`. Always inline all styles — no external CSS files, no build step.
- **Design system:** always load `general/design-spec` alongside this skill — it contains the five presets (colour tokens, typography, skeletons). This site defaults to **Atelier Ledger** unless the page type calls for another.
- **After writing files:** `git add docs/`, `git commit`, `git push` — GitHub Pages auto-deploys on push.
- **Preferred thinking:** `low` for copy-only updates; `medium` for new page layouts.
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

- **Default preset: Atelier Ledger.** Warm parchment tones, humanist serif for headings, generous whitespace. Use Porcelain Ops for a lighter/product-adjacent page if the content warrants it.
- **Homepage:** sparse. Name, one line of positioning, 2–3 links. No hero image.
- **Writing pages:** prose-first. Lora body, generous line-height (1.75+), max-width ~680px.
- **No JavaScript by default.** Add it only when interactivity is genuinely needed.
- **No framework, no build.** Plain HTML + inlined CSS. GitHub Pages serves it directly.

---

## GitHub Pages constraints

- Static files only — no server-side logic.
- Base URL: `https://maxsamne.github.io/one/` until a custom domain is set.
- Custom domain: create `docs/CNAME` containing just the bare domain (e.g. `maxsamne.com`). GitHub Pages picks it up automatically.
- All asset paths must be relative or use the `/one/` prefix.
