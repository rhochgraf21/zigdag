---
answer: fixed
by: robert
findings:
  - {rule: interface-order-to-remember, subject: arch.model.policy, key: arch-model-policy-interface-order-to-remember}
---
EffectRule.verdict takes the component and applies the rule's own exemptions, as DirectEffects.permits and ImportRule.allows do; combining takes the component too. for_component is gone, so there is no step to forget.
