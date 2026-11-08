"""What Python's own APIs mean to zigdag: which calls have which effects, and which types are standard wrappers."""

from __future__ import annotations

from collections.abc import Mapping

from zigdag.core.effects import Effect

BUILTINS_PREFIX = "builtins."  # how the scanner qualifies a built-in name: builtins.print
RECEIVERS = frozenset({"self", "cls"})  # what a method's first parameter is called: the object, or its class
MODULE_NAMES = frozenset({"__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__"})  # every module's
# Calls that only build a container from what they are given (DESIGN2 §4.1, planned-effects).
BUILDERS = frozenset(f"builtins.{n}" for n in ("list", "tuple", "dict", "set", "frozenset"))
STATICMETHOD = "builtins.staticmethod"
OPENERS = frozenset({"builtins.open", "io.open", "codecs.open", "pathlib.Path.open"})

READ, WRITE = Effect("read"), Effect("write")
STDOUT, STDERR, STDIN = Effect("stdout"), Effect("stderr"), Effect("stdin")
NETWORK, SYSCALL = Effect("network"), Effect("syscall")
RANDOM, TIME, ENV = Effect("random"), Effect("time"), Effect("env")
GLOBAL, IMPORT = Effect("global"), Effect("import")

# A qualified call, or a module whose every call has the effect. The longest matching prefix wins.
CALLS: Mapping[str, Effect] = {
    **dict.fromkeys(["subprocess", "os.system", "os.popen", "os.execv", "os.execve", "os.execvp", "os.execl",
                     "os.spawnv", "os.spawnl", "os.fork", "os.kill", "os.startfile", "multiprocessing",
                     "signal.signal", "pty"], SYSCALL),
    **dict.fromkeys(["socket", "urllib.request", "http.client", "requests", "httpx", "aiohttp", "urllib3",
                     "ftplib", "smtplib", "websockets", "ssl.create_default_context"], NETWORK),
    **dict.fromkeys(["os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.mkdir", "os.makedirs", "os.rename",
                     "os.renames", "os.replace", "os.chmod", "os.chown", "os.symlink", "os.link", "os.truncate",
                     "os.utime", "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree", "shutil.move",
                     "shutil.rmtree", "shutil.make_archive", "tempfile"], WRITE),
    **dict.fromkeys(["os.listdir", "os.scandir", "os.walk", "os.stat", "os.lstat", "os.path.exists",
                     "os.path.isfile", "os.path.isdir", "os.path.getsize", "os.path.getmtime", "os.path.islink",
                     "glob.glob", "glob.iglob", "pathlib.Path.cwd", "pathlib.Path.home"], READ),
    **dict.fromkeys(["os.getenv", "os.putenv", "os.getcwd", "os.path.expanduser"], ENV),
    **dict.fromkeys(["time.time", "time.time_ns", "time.monotonic", "time.monotonic_ns", "time.perf_counter",
                     "time.perf_counter_ns", "time.process_time", "time.localtime", "time.gmtime", "time.ctime",
                     "datetime.datetime.now", "datetime.datetime.utcnow", "datetime.datetime.today",
                     "datetime.date.today"], TIME),
    **dict.fromkeys(["random", "secrets", "os.urandom", "uuid.uuid1", "uuid.uuid4"], RANDOM),
    **dict.fromkeys(["logging"], STDERR),
    "builtins.input": STDIN,
    "builtins.breakpoint": STDIN,
    "builtins.print": STDOUT,  # print(file=...) is decided where the call is read
}

# Names that are effects when only touched, not called.
TOUCHED: Mapping[str, Effect] = {"sys.stdout": STDOUT, "sys.stderr": STDERR, "sys.stdin": STDIN, "os.environ": ENV}

# Methods that touch the file system whatever they are called on (pathlib's, mostly).
PATH_METHODS: Mapping[str, Effect] = {
    **dict.fromkeys(["read_text", "read_bytes", "iterdir", "glob", "rglob", "is_file", "is_dir", "exists",
                     "stat", "lstat", "readlink"], READ),
    **dict.fromkeys(["write_text", "write_bytes", "unlink", "mkdir", "rmdir", "touch", "symlink_to",
                     "hardlink_to", "chmod"], WRITE),
}

UNKNOWN_CALLS = frozenset({"builtins.eval", "builtins.exec", "builtins.__import__", "importlib.import_module",
                           "importlib.__import__", "builtins.compile"})

CONTAINERS = frozenset({
    *(f"builtins.{n}" for n in ("list", "tuple", "dict", "set", "frozenset", "type")),
    *(f"typing.{n}" for n in ("List", "Tuple", "Dict", "Set", "FrozenSet", "Type", "Iterable", "Iterator",
                              "Sequence", "Mapping", "MutableMapping", "MutableSequence", "MutableSet", "Collection",
                              "Callable", "Generator", "AsyncIterator", "AsyncIterable", "AsyncGenerator",
                              "Awaitable", "Coroutine", "AbstractSet", "ClassVar", "Final", "Deque", "DefaultDict",
                              "OrderedDict", "Counter", "ChainMap", "Required", "NotRequired", "ReadOnly")),
    *(f"collections.abc.{n}" for n in ("Iterable", "Iterator", "Sequence", "Mapping", "MutableMapping",
                                       "MutableSequence", "Set", "MutableSet", "Collection", "Callable", "Generator",
                                       "AsyncIterator", "AsyncIterable", "AsyncGenerator", "Awaitable", "Coroutine",
                                       "Container", "Reversible", "KeysView", "ValuesView", "ItemsView")),
    *(f"collections.{n}" for n in ("deque", "defaultdict", "OrderedDict", "Counter", "ChainMap")),
})
UNIONS = frozenset({"typing.Union", "typing.Optional"})
LITERALS = frozenset({"typing.Literal"})
ANNOTATED = frozenset({"typing.Annotated"})
ANYS = frozenset({"typing.Any", "builtins.object"})
BOOLS = frozenset({"builtins.bool"})
NAMED_TYPE_MAKERS = frozenset({"typing.NewType", "typing.TypeVar", "typing.ParamSpec", "typing.TypeVarTuple"})
TYPE_ALIAS = frozenset({"typing.TypeAlias"})

DEAL_HAS, DEAL_PURE, DEAL_SAFE, DEAL_RAISES = "deal.has", "deal.pure", "deal.safe", "deal.raises"
DEAL_CONTRACTS = frozenset({"deal.pre", "deal.post", "deal.ensure", "deal.inv", "deal.reason", "deal.example"})
HYPOTHESIS_GIVEN = "hypothesis.given"
DEAL_CASES = "deal.cases"

# Distributions whose import name is not their own name, normalised.
DISTRIBUTION_IMPORTS: Mapping[str, tuple[str, ...]] = {
    "pyyaml": ("yaml",), "beautifulsoup4": ("bs4",), "pillow": ("PIL",), "scikit_learn": ("sklearn",),
    "python_dateutil": ("dateutil",), "opencv_python": ("cv2",), "attrs": ("attr", "attrs"),
    "protobuf": ("google",), "pyjwt": ("jwt",), "python_dotenv": ("dotenv",), "msgpack_python": ("msgpack",),
    "pytest": ("_pytest",), "crosshair_tool": ("crosshair",),
}

ENUM_BASES = frozenset({"enum.Enum", "enum.StrEnum", "enum.IntEnum", "enum.Flag", "enum.IntFlag"})

# Abstractions (DESIGN2 §4.1, no-single-implementations): a protocol, or an abstract base class.
PROTOCOLS = frozenset({"typing.Protocol", "typing_extensions.Protocol"})
ABSTRACT_BASES = frozenset({"abc.ABC"})
ABSTRACT_METACLASSES = frozenset({"abc.ABCMeta"})
ABSTRACT_METHODS = frozenset({"abc.abstractmethod"})
METACLASS = "metaclass"  # the class keyword that names a metaclass

NO_MUTATE = "pragma: no mutate"  # a comment that tells mutmut to leave a line, or a block, unmutated
KEY_FIELD = "id"  # a field with this name is its class's identity
PRIMARY_KEY = "primary_key"  # an ORM's keyword marking a key column: mapped_column(primary_key=True)

# Methods that change the object they are called on: order.lines.append(line) changes order.lines in place.
MUTATORS = frozenset({"append", "extend", "insert", "remove", "pop", "clear", "update", "add", "discard",
                      "setdefault", "popitem", "sort", "reverse", "__setitem__", "__delitem__"})
SETATTR = frozenset({"builtins.setattr", "builtins.delattr"})

# Release points (DESIGN2 §4.1, data-flow): calls that make a value into plain text.
RELEASES = frozenset({"builtins.str", "builtins.repr", "builtins.format", "builtins.ascii", "builtins.bytes",
                      "json.dumps", "json.dump", "pickle.dumps", "pickle.dump", "marshal.dumps", "dataclasses.asdict",
                      "dataclasses.astuple", "yaml.dump", "yaml.safe_dump", "copyreg.pickle"})
F_STRING, PERCENT_FORMAT, FORMAT_METHOD = "an f-string", "% formatting", "str.format"
LOGGER_FACTORIES = frozenset({"logging.getLogger"})
LOGGING = "logging"
