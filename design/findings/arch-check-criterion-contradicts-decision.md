---
kind: question
station: requirements
source: critic
by: criterion-contradicts-decision
subject: arch.check
digest: a04d567900e6
evidence: When a finding has an answer, it shall never signal failure.
hint: "Narrow AC3 to answers that still hold, for example: 'When a finding has an accepted answer with a reason, it shall not signal failure; when a finding answered as fixed occurs again, it shall block.'"
---
The decision chose a ratchet in which fixed findings cannot return, but AC3 says any answered finding never signals failure, so a finding answered as fixed that reappears would pass. It is undecided whether a returning fixed finding blocks.
