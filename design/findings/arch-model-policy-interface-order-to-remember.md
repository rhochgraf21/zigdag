---
kind: question
station: interface
source: critic
by: interface-order-to-remember
subject: arch.model.policy
digest: "866dcaae241e"
evidence: "EffectRule.for_component(self, cid: ComponentId) -> EffectRule"
hint: "Make the verdict take the component, e.g. verdict(self, cid: ComponentId, effect: EffectKind), the way DirectEffects.permits and ImportRule.allows already do. Or have for_component return a distinct type, such as ComponentEffects, that is the only one with verdict."
---
The rule carries exempt components but verdict(effect) takes no component, so a caller gets a correct verdict only by remembering to call for_component(cid) first. Because for_component returns the same EffectRule type (Policy.for_component does the same), the types allow verdict on a rule that was never narrowed, which silently ignores the exemptions.
