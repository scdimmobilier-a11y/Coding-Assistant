"""nexus_unified.security.pickle_scan — analyse statique d'un flux pickle, sans jamais le charger.

Un pickle n'est pas un format de données : c'est un programme pour une
machine à pile, et `pickle.load` exécute toute fonction qu'il importe par
GLOBAL / STACK_GLOBAL / INST / OBJ puis appelle par REDUCE. L'analyse lit
les opcodes avec `pickletools.genops`, reconstitue chaque import
(module, nom) et le classe :

- DANGEREUX (CRITICAL) : exécution de commande, réseau, import dynamique,
  évaluation de code — tout ce qu'aucun poids légitime n'importe ;
- SÛR : reconstructeurs connus de PyTorch, NumPy, collections, scikit-learn ;
- INCONNU (MEDIUM) : ni l'un ni l'autre ; bloqué par défaut, à revoir.

Les chaînes du flux passent en plus par `ioc.scan_text` (C2, exfiltration).
"""
from __future__ import annotations

import io
import pickletools
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .findings import Finding, Severity, finding
from .ioc import scan_text

# Modules dont tout import est dangereux.
DANGEROUS_MODULES: Set[str] = {
    "os", "posix", "nt", "subprocess", "socket", "_socket", "sys", "shutil", "pty",
    "commands", "webbrowser", "ctypes", "_ctypes", "importlib", "runpy", "code",
    "codeop", "pdb", "bdb", "timeit", "multiprocessing", "asyncio", "threading",
    "_thread", "signal", "requests", "urllib", "urllib2", "urllib3", "http",
    "httplib", "ftplib", "smtplib", "telnetlib", "poplib", "imaplib", "paramiko",
    "aiohttp", "httpx", "pickle", "_pickle", "cPickle", "dill", "cloudpickle",
    "marshal", "zipimport", "pkgutil", "site", "fcntl",
    "resource", "mmap", "select", "selectors", "ssl", "dns", "xmlrpc",
    "venv", "ensurepip", "pip", "setuptools", "distutils", "torch.hub",
    "torch._inductor", "torch.utils.cpp_extension", "numpy.f2py", "numpy.testing",
    "IPython", "jupyter_client", "nbformat", "tensorflow.python.ops.script_ops",
}
# Noms dangereux dans des modules par ailleurs légitimes.
DANGEROUS_NAMES: Dict[str, Set[str]] = {
    "builtins": {"eval", "exec", "compile", "open", "__import__", "getattr", "setattr",
                 "delattr", "globals", "locals", "vars", "input", "breakpoint",
                 "exit", "quit", "help", "memoryview", "__build_class__"},
    "__builtin__": {"eval", "exec", "compile", "open", "__import__", "getattr",
                    "setattr", "execfile", "file", "input", "raw_input"},
    "types": {"CodeType", "FunctionType", "LambdaType", "MethodType", "ModuleType"},
    "io": {"open", "open_code", "FileIO"},
    "_io": {"open", "open_code", "FileIO"},
    "numpy": {"load", "fromfile", "loadtxt", "genfromtxt", "save"},
    "numpy.lib.npyio": {"load", "loadtxt"},
    "torch": {"load", "save", "compile", "jit"},
    "torch.serialization": {"load", "_load"},
    "pandas": {"read_pickle", "eval", "read_csv"},
}
# Gadgets : inoffensifs isolément, briques classiques des chaînes d'exploitation.
GADGET_NAMES: Dict[str, Set[str]] = {
    "operator": {"attrgetter", "methodcaller", "itemgetter", "getitem"},
    "functools": {"partial", "reduce"},
    "copyreg": {"__newobj__", "__newobj_ex__"},
}
# Imports reconnus sûrs (préfixes de module ou couples exacts).
SAFE_EXACT: Set[Tuple[str, str]] = {
    ("collections", "OrderedDict"), ("collections", "defaultdict"),
    ("collections", "deque"), ("collections", "Counter"), ("collections", "namedtuple"),
    ("builtins", "set"), ("builtins", "frozenset"), ("builtins", "dict"),
    ("builtins", "list"), ("builtins", "tuple"), ("builtins", "bytearray"),
    ("builtins", "bytes"), ("builtins", "complex"), ("builtins", "slice"),
    ("builtins", "range"), ("builtins", "int"), ("builtins", "float"),
    ("builtins", "str"), ("builtins", "bool"), ("builtins", "object"),
    ("__builtin__", "set"), ("__builtin__", "frozenset"), ("__builtin__", "object"),
    ("_codecs", "encode"),                  # NumPy sérialise ses octets ainsi
    ("copyreg", "_reconstructor"), ("copy_reg", "_reconstructor"),
    ("datetime", "datetime"), ("datetime", "date"), ("datetime", "time"),
    ("datetime", "timedelta"), ("datetime", "timezone"), ("decimal", "Decimal"),
    ("fractions", "Fraction"), ("uuid", "UUID"), ("enum", "Enum"),
    ("argparse", "Namespace"), ("pathlib", "PosixPath"), ("pathlib", "PurePosixPath"),
    ("pathlib", "WindowsPath"), ("pathlib", "PureWindowsPath"),
    ("torch", "Size"), ("torch", "device"), ("torch", "dtype"), ("torch", "float32"),
    ("torch", "float16"), ("torch", "bfloat16"), ("torch", "int64"), ("torch", "int32"),
    ("torch", "int8"), ("torch", "uint8"), ("torch", "bool"),
    ("numpy", "dtype"), ("numpy", "ndarray"), ("numpy", "float32"), ("numpy", "float64"),
    ("numpy", "int64"), ("numpy", "int32"), ("numpy", "bool_"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy.core.multiarray", "scalar"),
    ("numpy._core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "scalar"),
    ("numpy.random", "__RandomState_ctor"), ("numpy.random._pickle", "__randomstate_ctor"),
    ("numpy.random._pickle", "__bit_generator_ctor"),
}
SAFE_PREFIXES: Tuple[str, ...] = (
    "torch._utils.", "torch.nn.modules.", "torch.nn.parameter.", "torch.storage.",
    "torch._tensor.", "torch.optim.", "torch.amp.",
    "sklearn.", "scipy.sparse.", "xgboost.core.", "lightgbm.basic.",
    "pandas.core.", "pandas._libs.", "transformers.configuration_",
    "transformers.tokenization_", "tokenizers.", "sentencepiece.",
)
SAFE_TORCH_STORAGES = {
    "FloatStorage", "DoubleStorage", "HalfStorage", "BFloat16Storage", "LongStorage",
    "IntStorage", "ShortStorage", "CharStorage", "ByteStorage", "BoolStorage",
    "ComplexFloatStorage", "ComplexDoubleStorage", "UntypedStorage", "TypedStorage",
}
_STRING_OPS = {"SHORT_BINUNICODE", "BINUNICODE", "BINUNICODE8", "UNICODE",
               "SHORT_BINSTRING", "BINSTRING", "STRING", "SHORT_BINBYTES",
               "BINBYTES", "BINBYTES8"}
_PUT_OPS = {"PUT", "BINPUT", "LONG_BINPUT", "MEMOIZE"}
_GET_OPS = {"GET", "BINGET", "LONG_BINGET"}

MAX_OPS = 5_000_000


def classify_global(module: str, name: str) -> str:
    """Retourne 'dangerous', 'gadget', 'safe' ou 'unknown'."""
    module = module.strip()
    name = name.strip()
    root = module.split(".")[0]
    full = f"{module}.{name}"
    if module in DANGEROUS_MODULES or root in DANGEROUS_MODULES:
        return "dangerous"
    if any(full == d or full.startswith(d + ".") for d in DANGEROUS_MODULES if "." in d):
        return "dangerous"
    if name in DANGEROUS_NAMES.get(module, set()):
        return "dangerous"
    if name in GADGET_NAMES.get(module, set()):
        return "gadget"
    if (module, name) in SAFE_EXACT:
        return "safe"
    if module == "torch" and name in SAFE_TORCH_STORAGES:
        return "safe"
    if any(full.startswith(p) for p in SAFE_PREFIXES):
        return "safe"
    return "unknown"


def _iter_pickles(data: bytes):
    """Itère sur les pickles concaténés d'un flux (format joblib, multiples dumps)."""
    stream = io.BytesIO(data)
    while stream.tell() < len(data):
        start = stream.tell()
        ops = []
        try:
            for op in pickletools.genops(stream):
                ops.append(op)
                if len(ops) > MAX_OPS:
                    raise ValueError("flux pickle démesuré")
                if op[0].name == "STOP":
                    break
        except Exception as exc:  # noqa: BLE001 — tout échec d'analyse est un constat
            yield start, ops, exc
            return
        yield start, ops, None
        # Ignore le bourrage éventuel entre deux pickles (joblib aligne les tableaux).
        rest = data[stream.tell():stream.tell() + 1]
        if not rest or rest[0] != 0x80:
            return


def scan_pickle_bytes(data: bytes, file: str, analyzer: str = "pickle") -> List[Finding]:
    out: List[Finding] = []
    if not data:
        return out
    strings_seen: List[str] = []
    imports: List[Tuple[str, str, int]] = []
    reduce_count = 0
    n_pickles = 0
    for start, ops, err in _iter_pickles(data):
        n_pickles += 1
        recent: List[str] = []
        memo: Dict[int, str] = {}
        next_memo = 0
        for opcode, arg, pos in ops:
            name = opcode.name
            if name in _STRING_OPS:
                val = arg.decode("latin-1", "replace") if isinstance(arg, (bytes, bytearray)) else str(arg)
                recent.append(val)
                if len(strings_seen) < 20000:
                    strings_seen.append(val)
            elif name in _PUT_OPS:
                idx = next_memo if name == "MEMOIZE" else int(arg)
                if name == "MEMOIZE":
                    next_memo += 1
                if recent:
                    memo[idx] = recent[-1]
            elif name in _GET_OPS:
                if int(arg) in memo:
                    recent.append(memo[int(arg)])
            elif name in ("GLOBAL", "INST"):
                mod, _, nm = str(arg).partition(" ")
                imports.append((mod, nm, pos))
            elif name == "STACK_GLOBAL":
                if len(recent) >= 2:
                    imports.append((recent[-2], recent[-1], pos))
                else:
                    out.append(finding("pickle.unresolved_stack_global", Severity.HIGH, file,
                                       "import STACK_GLOBAL dont le nom n'a pas pu être reconstitué",
                                       f"offset {pos}", "malware", analyzer))
            elif name in ("REDUCE", "BUILD", "OBJ", "NEWOBJ", "NEWOBJ_EX"):
                if name == "REDUCE":
                    reduce_count += 1
        if err is not None:
            sev = Severity.HIGH if n_pickles == 1 and not ops else Severity.MEDIUM
            out.append(finding("pickle.malformed", sev, file,
                               f"flux pickle illisible après {len(ops)} opcodes : {type(err).__name__}",
                               str(err)[:120], "format", analyzer))

    seen: Set[Tuple[str, str]] = set()
    for mod, nm, pos in imports:
        if (mod, nm) in seen:
            continue
        seen.add((mod, nm))
        cls = classify_global(mod, nm)
        if cls == "dangerous":
            out.append(finding("pickle.dangerous_global", Severity.CRITICAL, file,
                               "le pickle importe une fonction capable d'exécuter du code ou d'ouvrir le réseau",
                               f"{mod}.{nm} @ {pos}", "malware", analyzer))
        elif cls == "gadget":
            out.append(finding("pickle.gadget_global", Severity.HIGH, file,
                               "le pickle importe une brique classique de chaîne d'exploitation",
                               f"{mod}.{nm} @ {pos}", "malware", analyzer))
        elif cls == "unknown":
            out.append(finding("pickle.unknown_global", Severity.MEDIUM, file,
                               "import absent de la liste des reconstructeurs connus",
                               f"{mod}.{nm} @ {pos}", "malware", analyzer))
    if strings_seen:
        out.extend(scan_text("\n".join(strings_seen), file, executable=True, analyzer=analyzer))
    if n_pickles > 1:
        out.append(finding("pickle.multiple_streams", Severity.LOW, file,
                           f"{n_pickles} flux pickle concaténés", "", "format", analyzer))
    return out


def is_probably_pickle(head: bytes) -> bool:
    """Protocole 2+ commence par 0x80 <proto> ; protocole 0/1 par un opcode texte."""
    if len(head) >= 2 and head[0] == 0x80 and 2 <= head[1] <= 5:
        return True
    return bool(head[:1]) and head[:1] in (b"(", b"c", b"]", b"}", b"I", b"S", b"V")
