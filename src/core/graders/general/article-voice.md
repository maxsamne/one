---
suggested_for_skills:
  - general/article-writer/SKILL.md
---

> Grades long-form writing for voice, structural adherence, and depth of insight.

## Criteria

### follows_skill (weight: 2)
Does the output follow the structural and voice rules of the attached skill file(s)?
Inspect the active skills the author was working from, but keep the user's requested
scope primary. For article revision prompts that ask for framing, prose, argument,
or voice changes, grade the writing against the article-writer guidance and do not
request CSS, layout, typography, or article-design cleanup unless the user explicitly
asked for presentation changes or the design defect makes the article unreadable.
Cite exact passages where the work deviates — wrong heading hierarchy, missing
sections, abandoned section templates, voice that doesn't match the skill's stated
tone.

### tone_and_voice (weight: 1)
Plain, confident, non-corporate, and specific. No hedging ("perhaps", "it could be argued"),
no buzzwords ("leverage", "synergize"), no LLM-flavoured filler ("In conclusion,
this is a fascinating topic..."). Avoid cliché, inflated, generic, or cringe phrasing;
do not use hype lines like "the next big unlock", "revolutionary", or "game-changing".
Sentences should sound like a thoughtful person talking, not a marketing department writing.
First-person perspective is fine, but "I" must not dominate sentence openings.
If more than 3 consecutive sentences start with "I", or more than ~25% of sentences
in a paragraph begin with "I", flag it — vary the opening with a noun phrase,
a dependent clause, or a concrete observation that leads to the judgment.

### intellectual_depth (weight: 2)
Does the piece make non-obvious connections, show genuine curiosity, and reward a
careful reader? Length does NOT matter — a concise piece can score 5/5. Look for:
specificity over abstraction, surprising-but-defensible claims, examples that
actually illustrate the point. Penalize: restating the prompt, padding, lists of
generic facts the reader could have produced themselves.
