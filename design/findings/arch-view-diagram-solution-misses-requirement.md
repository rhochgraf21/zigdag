---
kind: question
station: solution
source: critic
by: solution-misses-requirement
subject: arch.view.diagram
digest: "871aa1d75432"
evidence: A diagram model rendered to Mermaid, Graphviz and SVG, with overlays for effects, coupling and change
hint: Add the stability mechanism to the solution, for example 'with node order and placement derived from stable ids, so a small design change moves only the parts it touches', and give it a criterion.
---
The requirement asks for forms that stay stable across revisions, but the solution says nothing about how layout or ordering stays put when the design changes. AC1 covers only the same design giving the same output, so a small design change could still reshuffle the whole picture.
