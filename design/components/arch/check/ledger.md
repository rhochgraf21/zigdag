---
kind: component
realizes: Keep what critics, people and agents noticed, with every answer given to any finding
solution: Plain-text finding and answer files under design, applied to every check
hides: How findings and answers are stored and matched
uses: [engine, model.codec, model.graph, model.ids, model.schema]
status: specified
---
## Acceptance criteria
- AC1: When a finding has an answer with a reason, the check shall report it and shall not let it block.
- AC2: When an answer covers findings that no longer occur, the check shall point that out.
- AC3: If an answer gives no reason, then the check shall report an error.
- AC4: When an escaped finding is answered as fixed or accepted without a countermeasure, the check shall question the answer.
- AC5: When a finding's subject has changed since it was noticed, the finding shall say so.
- AC6: Ledger files shall read back exactly as they were written.
