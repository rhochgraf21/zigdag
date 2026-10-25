---
kind: question
station: interface
source: critic
by: interface-leaks-storage
subject: arch.integrate.server
digest: "70124b775706"
evidence: "make_server(reviewing: Reviewing, port: Port=Port(0)) -> ThreadingHTTPServer"
hint: Return an arch-owned handle that exposes only the bound URL and a stop or close method, or keep the server internal behind serve().
---
The part hides HTTP, but this function returns the standard library's HTTP server class. Callers are tied to http.server, and the part cannot change its transport without changing them.
