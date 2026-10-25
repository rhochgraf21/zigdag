---
answer: fixed
by: robert
findings:
  - {rule: criterion-adds-function, subject: arch.model.codec, key: arch-model-codec-criterion-adds-function}
---
Widened the requirement to files in the design's format and the values they hold, which covers both design nodes and ledger entries, and reworded AC4 as the codec's own function, with no obligation on other stores.
