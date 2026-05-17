# The Mechanical Slavery of Knowledge Work

"All unintellectual labour, all monotonous, dull labour, all labour that deals with dreadful things, and involves unpleasant conditions, must be done by machinery. Machinery must work for us."
— Oscar Wilde, The Soul of Man Under Socialism (1891)

Wilde was writing about coal mines in 1891. But he might as well have been writing about AI in 2026. If you watch how most knowledge workers actually spend their day, you see the same pattern. Tedium, in place of danger. A huge share of the hours are spent on things that don't require thinking at all.

Regardless of what you do, you open your inbox, there are 40 messages, maybe five require judgment. The rest are status pings, scheduling, someone forwarding something you need to skim so you can update a doc so someone else can update a slide. You copy action items from meeting notes into the project tracker. You chase a Slack thread to find out what actually got decided — it wasn't in the summary, it was the reply four messages down. You reformat numbers into a deck. None of this is thinking. All of it is hours, and a whole lot of anxiety.

When was the last time you felt like this going through your email or Slack?

The modern knowledge worker is a human integration layer between software that doesn't talk to itself. And we're trying to build better highways instead of better cities.

If you look at what people actually do at a computer all day, it collapses into about five things. Five kinds of cognitive work.

Attention — what needs my focus right now. Commitment — what I've agreed to do, and by when. Artifact — a thing I'm making or maintaining. Context — accumulated knowledge bearing on a decision. Coordination — synchronizing with other people so the previous four don't collide.

Every productivity tool you've used serves some subset of these. A document editor is Artifact with a thin layer of Coordination. A project tracker is Commitment with some Attention routing. Email is Coordination that quietly doubles as Context storage and Commitment tracking, which is why your inbox becomes a todo list even though it's terrible at it. Calendar is Commitment plus Attention, minus everything else.

The interesting part is that no tool serves all of them (nor should they). And the gaps between tools are exactly where work breaks down. You finish a meeting (Coordination), open a doc to capture what was decided (Artifact), realize you need to update a deadline (Commitment), check Slack to confirm something someone said (Context), and then lose twenty minutes because the thing that needed your Attention was in a different tab entirely. The friction isn't in any single tool. It's in the seams between them.

## The iPhone and OLE — two precedents for unifying the seams

This is why "integrations" don't actually fix the problem. Connecting Notion to Slack to Google Calendar doesn't unify the five — it creates a plumbing layer between tools that each still model only their own slice. The context that matters — why this artifact relates to that commitment, who last changed the state of this coordination thread — doesn't survive the trip through a webhook.

Can a single system serve all five natively by treating all five as first-class objects in the same data model, so that the relationships between them are as real as the objects themselves.

If you actually try to spec out what that unified data model requires, the list of primitives is pretty short. Every productivity tool you've ever used is some combination of these, wrapped in different UI and sold as a different product category.

## The Workspace That Doesn't Exist

The primitives consistently weakest across every tool — Trigger, Provenance, Context, Diff — are the ones that connect things: why something exists, what spawned it, what changed, and what should react. A Google Doc has no idea it was created because of a Slack thread about a client request that came in via email. You know that. The software doesn't. The context graph — the web of relationships between artifacts, decisions, conversations, and people — is maintained entirely in your head. It's the most important layer, it exists in no product, and it's exactly what an AI layer is positioned to provide. It's the workspace that doesn't exist.

The models are good enough. They can write, reason, summarize, and draft. But today you're stuck between two options: siloed AI features inside single-primitive editors that can't see the context graph, or manual context-gathering across tools, one-shotting output in Claude or ChatGPT, then hauling it back into Word or Slides to iterate endlessly. Both work well for short-horizon, self-contained, containerized tasks. But neither feel like the final form factor.

The obvious response is to connect the silos — protocols like MCP that let AI fetch data from Slack, Drive, your calendar, whatever. And that's useful. But fetching fragments on demand is not the same as understanding. The AI gets snapshots, not a living model. It can pull a Slack message and a Google Doc into the same prompt, but it doesn't know that the message caused the doc. The relationships between things — the part that actually constitutes context — stay invisible. You're building better highways between cities. The argument here is that you need one city where everything is walkable.

When the primitives share an environment, the boundaries dissolve. An outline becomes a table. A thread becomes a task. A meeting triggers a set of doc revisions. The AI doesn't just edit within one document type — it moves fluidly across all of them, because from its perspective they're all structured data in the same graph. You say "turn the action items from Tuesday's meeting into tasks on the board and update the brief accordingly" and it works, because it sees the meeting, the board, and the brief in one persistent context.

Email, calendar, and messaging become native context, not integrations you configure. The AI that helps you revise a strategy doc already knows the meeting changed the scope, because it was there. The context graph stops living in your head and starts living in the software.

And once it does, something else shifts. The AI no longer needs to wait for a prompt. Every AI product today starts with a text box — write something clever and maybe you'll get something useful back. That's five steps where the human does everything and the AI just responds. But if the system already holds the context graph — your meetings, your commitments, the state of every artifact — the AI can observe, infer, and act before you ask. Your Monday morning briefing is prepped because the AI watched the calendar. The status update is drafted because it saw what shipped. The three emails that matter are flagged because it knows the project state. The chat box doesn't disappear, but it stops being the front door. It becomes the thing you reach for after the system has already earned your attention by doing the work you would have spent the first two hours on. Action first, conversation second. TikTok won the attention war not by asking users what they wanted to watch, but by observing and serving. The same inversion applies here — but it only works if the AI can see the full graph. A siloed assistant trapped in one app doesn't know enough to act proactively. A unified system does.

Imagine spending your days actually creating — designing something that didn't exist before, writing the piece that makes people feel something, building the thing that's genuinely new. Not formatting slides. Not chasing status updates. Not copy-pasting between apps. Creating.

Time is finite, and every minute spent on admin is a minute not spent making something beautiful. The mechanical slavery isn't just inefficient — it's tragic. People with real taste, real craft, real ideas, burning hours on work that a machine should be doing. The loss isn't measured in productivity. It's measured in all the things that never got made.

The goal isn't a better workspace. It's getting the admin out of the way so people can do what they're actually here to do — bring new things into the world.
