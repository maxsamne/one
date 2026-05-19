---
judge: gemini:gemini-3.1-pro-preview
auto_attach_with_any_grader: true
needs_images: true
---

> Auto-attached whenever any other grader is present. Judges whether the output actually answers what the user asked for, and — when reference images are attached — whether it takes real inspiration from them. Uses a vision-capable judge so it can look at the user's references and the produced artifact together.

## Criteria

### prompt_satisfaction (weight: 3)
Does the output address what the user actually asked for? Read the original task prompt above carefully. Score against the user's literal request, not against what a sensible person might have asked for instead. Check:
- Every concrete ask in the prompt has a corresponding piece of the output. If the user asked for X and Y, both X and Y must be visible.
- Negative constraints are honoured ("don't add features", "same text", "no JavaScript"). A confirmed violation is a score of 2 or lower.
- Implicit asks (a tone the user set, a domain they framed the task in) are respected.
- The output is not a thin gesture toward the prompt; it is a substantive response to it.
A response that follows attached skills perfectly but ignores the user's actual request is a low score — skill compliance is not a substitute for answering the prompt. Cite the specific part of the prompt that was missed.

### reference_fidelity (weight: 3)
When the user attached reference images, did the output take real inspiration from them? Skip this criterion (score 5) when no images were attached. When images were attached, check:
- The composition, density, and visual rhythm of the output echoes the references. A reference with a generous hero diagram and three feature columns should not produce a sparse name-and-two-links page.
- Colour palette, type voice, and surface treatment draw from the references — not just "in the same family", but visibly inspired.
- Where the references show a specific UI element (hero, card grid, navigation pattern), the output adopts a comparable element unless the user explicitly said otherwise.
- Generated imagery (if any) matches the reference's image style — illustration vs photograph, palette, mood.
"Heavy inspiration" does not mean copy. The output may translate the reference into the user's design system, but the family resemblance must be obvious at a glance. Cite specific elements of the reference that were ignored.
