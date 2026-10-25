---
kind: question
station: requirements
source: critic
by: criterion-contradicts-decision
subject: arch.guide.infer
digest: "796b1a916768"
evidence: "`arch init` shall write the inferred design and a baseline of whatever errors remain"
hint: Restate AC5 as what infer returns (for example, the proposed operations are enough that, once applied and baselined, the first check passes), and move the `arch init` write-and-baseline criterion to the integrate component that owns the command.
---
The decision makes infer a heuristic advisor that only proposes design operations, but AC5 has it write the design and a baseline, which is a command's side effect. The two disagree on whether this part writes anything, and infer does not use check or the workspace, so it cannot meet AC5 at all.
