"""What the TypeScript adapter knows of Node and the browser (DESIGN2 §5.2): which calls have which effect, which
modules come with Node, and which generic types are standard wrappers around their arguments."""

from __future__ import annotations

from collections.abc import Mapping

from zigdag.core.effects import Effect
from zigdag.core.names import Library

READ, WRITE, NETWORK, SYSCALL = Effect("read"), Effect("write"), Effect("network"), Effect("syscall")
STDOUT, STDERR, STDIN = Effect("stdout"), Effect("stderr"), Effect("stdin")
RANDOM, TIME, ENV = Effect("random"), Effect("time"), Effect("env")

NODE_SCHEME = "node:"  # how a module that comes with Node may be written: node:fs
FILE_SYSTEM = "fs"  # Node's file system module, whose calls read or write by their names
# How a file system call's name begins when it only reads; every other one changes the disk.
FILE_READS = ("read", "exists", "stat", "lstat", "fstat", "access", "opendir", "createReadStream", "watch", "realpath")
_FS_PROMISES = "promises."  # fs.promises.readFile: the same calls, returning promises

# A qualified call, or a module or global whose every call has the effect. The longest matching prefix wins.
CALLS: Mapping[str, Effect] = {
    **dict.fromkeys(["child_process", "worker_threads", "cluster", "process.exit", "process.kill", "process.abort"],
                    SYSCALL),
    **dict.fromkeys(["http", "https", "http2", "net", "dgram", "dns", "tls", "fetch", "XMLHttpRequest", "WebSocket",
                     "EventSource", "navigator.sendBeacon", "axios", "node-fetch", "undici", "got", "ws"], NETWORK),
    **dict.fromkeys(["console.log", "console.info", "console.debug", "console.table", "console.dir",
                     "process.stdout"], STDOUT),
    **dict.fromkeys(["console.error", "console.warn", "console.trace", "process.stderr"], STDERR),
    **dict.fromkeys(["process.stdin", "readline", "prompt"], STDIN),
    **dict.fromkeys(["Date.now", "performance.now", "process.hrtime", "process.uptime"], TIME),
    **dict.fromkeys(["Math.random", "crypto.randomUUID", "crypto.randomBytes", "crypto.randomInt",
                     "crypto.getRandomValues"], RANDOM),
    **dict.fromkeys(["process.cwd", "process.chdir", "os.homedir", "os.hostname", "os.userInfo"], ENV),
}

# Names that are effects when only touched, not called.
TOUCHED: Mapping[str, Effect] = {"process.env": ENV, "process.argv": ENV}

CLOCK = "Date"  # new Date() with no argument reads the clock; with one, it only converts
UNKNOWN_CALLS = frozenset({"eval", "Function"})  # code made from text, which cannot be read
REQUIRE, DYNAMIC_IMPORT = "require", "import"

# The names that are there without being imported, and are read as written when nothing in the file shadows them.
GLOBALS = frozenset({"fetch", "console", "process", "Date", "Math", "crypto", "performance", "navigator", "eval",
                     "Function", "XMLHttpRequest", "WebSocket", "EventSource", "prompt", REQUIRE, "JSON", "String",
                     "Array", "Object", "Map", "Set", "Number", "Boolean"})

# Calls that only build a container from what they are given (DESIGN2 §4.1, planned-effects).
BUILDERS = frozenset({"Array", "Array.from", "Array.of", "Object.fromEntries", "Object.assign", "Object.freeze",
                      "Map", "Set"})
# Calls that make a value into plain text: where what a value holds leaves its type behind (DESIGN2 §4.1, data-flow).
RELEASES = frozenset({"JSON.stringify", "String"})
RELEASING_METHODS = frozenset({"toString", "toJSON", "toISOString", "toFixed"})  # the same, called on the value
TEMPLATE = "a template"  # what a value written into a text with ${...} is released through

# The modules that come with Node.
STANDARD: frozenset[Library] = frozenset(Library(name) for name in {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram",
    "diagnostics_channel", "dns", "domain", "events", "fs", "http", "http2", "https", "inspector", "module", "net",
    "os", "path", "perf_hooks", "process", "punycode", "querystring", "readline", "repl", "stream",
    "string_decoder", "test", "timers", "tls", "trace_events", "tty", "url", "util", "v8", "vm", "wasi",
    "worker_threads", "zlib",
})

# Generic types that only wrap their arguments: a value of one is, for the design, a value of what it holds.
CONTAINERS = frozenset({
    "Array", "ReadonlyArray", "Promise", "PromiseLike", "Map", "ReadonlyMap", "WeakMap", "Set", "ReadonlySet",
    "WeakSet", "Record", "Partial", "Required", "Readonly", "Pick", "Omit", "NonNullable", "Awaited", "Iterable",
    "IterableIterator", "Iterator", "AsyncIterable", "AsyncIterableIterator", "Generator", "AsyncGenerator",
})
BUILTINS_PREFIX = "builtins."  # how a type the language itself defines is qualified: builtins.string
NOTHING = frozenset({"null", "undefined", "void", "never"})  # the types of no value
ANYTHING = frozenset({"any", "unknown", "object"})  # the types that say nothing of a value
TRUTH = "boolean"

# Where a contract's words come from unless a project names a module of its own: the library that has them.
CONTRACT_LIBRARY = "ts-code-contracts"
# The calls that state what a function promises: what must hold of what it is given, and of what it gives back.
# The same words with NonNullish also hand the value on.
CONTRACT_CALLS = frozenset({"requires", "ensures", "requiresNonNullish", "ensuresNonNullish"})

# Methods that change what they are called on, whatever it holds.
MUTATORS = frozenset({"push", "pop", "shift", "unshift", "splice", "sort", "reverse", "fill", "copyWithin", "set",
                      "add", "delete", "clear"})


def effect_of(callee: str) -> Effect | None:
    """The effect a call to a qualified name starts: by the longest prefix that is known, and for the file system by
    whether the call's own name is a read's."""
    if callee == FILE_SYSTEM or callee.startswith(f"{FILE_SYSTEM}."):
        method = callee.removeprefix(f"{FILE_SYSTEM}.").removeprefix(_FS_PROMISES)
        return READ if method.startswith(FILE_READS) else WRITE
    parts = callee.split(".")
    return next((CALLS[known] for n in range(len(parts), 0, -1) if (known := ".".join(parts[:n])) in CALLS), None)
