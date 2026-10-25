---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.model.codec
digest: "47165246da93"
evidence: it shall write them through the codec from plain values
hint: Either widen realizes to cover documents in the design format built from plain values, or give that function its own part, and record 'other stores write through the codec' as a constraint on them.
---
The requirement is to convert between design files and nodes, but this AC4 adds a second function: writing other stores' files from plain values and reading them back. It also places an obligation on those other stores that their own designs do not show.
