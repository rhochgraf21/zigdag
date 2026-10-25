---
kind: question
station: interface
source: critic
by: interface-flag-picks-behaviour
subject: arch.integrate.agent
digest: b4b96467138a
evidence: "handle(event: HookEvent, ws: Workspace, payload: HookPayload) -> HookResponse"
hint: Split it into two functions, for example orient(ws) -> HookResponse and check_edit(ws, payload) -> HookResponse, and let the CLI map the hook event name to the right one.
---
The event enum chooses between two different behaviours that the decision records: session-start orientation and the post-edit check for blocking findings. One signature then serves both, so the orientation path has to accept an edit payload it has no use for.
