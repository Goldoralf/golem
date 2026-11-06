---
name: embedded-ux
description: Critique or design golem's touch UI (rack app at 1024×600 that never scrolls, top bar with five hubs; phone Companion at 390×844) with the golem-embedded-ux agent. It renders the real app with headless Chrome and critiques the actual pixels. Optional argument — a route (live, designer, songs/…, library/…, system/…) or a page file.
user-invocable: true
disable-model-invocation: false
agent: golem-embedded-ux
---

Ask the golem-embedded-ux agent to handle:

$ARGUMENTS

The agent applies "full screen, never scroll → navigate (tabs, drill-in, paged grid, drawer)", renders the real app
with `google-chrome --headless` (bridge on http://localhost:8770/app/) at 1024×600 — and 390×844 for the phone
Companion — intercepting every write to `/api/` when it interacts, and respects the shell in
`docs/ui-architecture.md` (top bar, page action published with `setTopAction`, touch targets ≥ 44 px). It also checks
English labels, the `golem` brand spelling, prefixed CSS state classes and nodes not rendered rather than `hidden`.
It returns a ranked punch-list and a layout decision. With no argument, it looks at the pages changed most recently
(`git status app/`).
