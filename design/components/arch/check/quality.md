---
kind: component
realizes: Judge how easy the code's interfaces are to use and to change
solution: Rules over the code facts for descriptions, depth, parameters that pick behaviour, narrow interfaces and abstractions with one implementation
hides: The measures and thresholds of interface quality
uses: [engine, model.graph, model.ids, realize.facts, realize.mapping, conformance]
status: specified
---
## Acceptance criteria
- AC1: When a public class, or a public function or field with a word that none of its types' names contains, has no description and implements no described base-class method, the check shall report a defect at the interface station.
- AC2: When every word of a description, apart from filler words such as 'the' and 'of', also appears in its signature, the check shall report that it only repeats its name and type.
- AC3: When a part that hides a decision shows at least 8 names and parameters with fewer than 3 lines of code behind each, the check shall ask whether it is shallow.
- AC4: When a public function branches on a parameter whose type is an enum or a flag, the check shall ask whether that parameter picks the behaviour.
- AC5: When a public function reads one field of a parameter whose type has at least 4 public fields, and never uses it whole, the check shall ask whether it should take that field instead.
- AC6: When a protocol has exactly one class that defines all its methods, the check shall ask whether the abstraction is needed yet.

