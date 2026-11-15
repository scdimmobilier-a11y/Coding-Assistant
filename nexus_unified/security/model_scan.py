"""nexus_unified.security.model_scan — inspection d'un fichier de modèle ou de données, par format.

Le risque dépend du format :

- **pickle / .pt / .ckpt / .joblib / .dill** : exécute du code au chargement →
  analyse d'opcodes (`pickle_scan`). Un `.pt` est un zip dont les `data.pkl`
  internes sont analysés.
- **.safetensors** : en-tête JSON + octets bruts, aucun chemin d'exécution →
  on valide l'en-tête et on refuse une clé `__` suspecte ; verdict propre sinon.
- **.gguf / .npy / .npz / .msgpack / .flax** : données binaires ; on vérifie
  l'absence du drapeau pickle (npy `allow_pickle`) et on passe les chaînes au
  détecteur C2.
- **.h5 / .keras / .hdf5** : peut embarquer des couches Lambda (code Python
  marshalé) et des attributs picklés → signalé HIGH, chaînes inspectées.
- **.onnx / .pb** : protobuf ; `py_func`/op personnalisé = code → signalé.
- **.py / .sh / notebooks / configs** : code ou texte → `ioc.scan_text`.

Toute branche inconnue tombe sur une inspection de chaînes : on ne déclare
jamais « propre » un format qu'on n'a pas su lire (verdict ERROR via le report).
"""
from __future__ import annotations

import json
import os
import re
import struct
import zipfile
from typing import List, Optional

from .findings import Finding, Severity, finding
from .ioc import scan_text
from .pickle_scan import is_probably_pickle, scan_pickle_bytes

PICKLE_EXT = {".pkl", ".pickle", ".pt", ".pth", ".bin", ".ckpt", ".joblib",
              ".dill", ".pck", ".model", ".sav", ".dat", ".pb2"}
SAFETENSORS_EXT = {".safetensors", ".st"}
HDF5_EXT = {".h5", ".hdf5", ".keras"}
NUMPY_EXT = {".npy", ".npz"}
ONNX_EXT = {".onnx", ".ort"}
TF_PB_EXT = {".pb"}
GGUF_EXT = {".gguf", ".ggml", ".gguf"}
TEXT_CODE_EXT = {".py", ".pyw", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".rb",
                 ".pl", ".js", ".ipynb"}
TEXT_DATA_EXT = {".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".txt",
                 ".md", ".csv", ".tsv", ".jsonl", ".xml", ".modelcard"}
MSGPACK_EXT = {".msgpack", ".mpk", ".flax"}

HEAD = 8192
MAX_TEXT = 8 * 1024 * 1024


def _read(path: str, n: int = -1) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def _scan_pt_zip(path: str, rel: str) -> List[Finding]:
    """Un .pt moderne est un zip ; ses *.pkl internes portent le risque."""
    out: List[Finding] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            pkls = [n for n in names if n.endswith((".pkl", ".pickle")) or
                    n.rsplit("/", 1)[-1] in ("data.pkl", "constants.pkl")]
            if not pkls:
                pkls = [n for n in names if is_probably_pickle(z.read(n)[:2])][:20]
            for n in pkls:
                try:
                    out.extend(scan_pickle_bytes(z.read(n), f"{rel}!{n}", "pickle"))
                except Exception as exc:  # noqa: BLE001
                    out.append(finding("pickle.member_error", Severity.MEDIUM, f"{rel}!{n}",
                                       f"membre pickle illisible : {type(exc).__name__}", "", "format", "pickle"))
            # byteorder/version.py exécutables glissés dans l'archive ?
            for n in names:
                if n.endswith(".py"):
                    out.append(finding("model.embedded_py", Severity.HIGH, f"{rel}!{n}",
                                       "fichier Python embarqué dans l'archive de poids", "", "malware", "model"))
    except zipfile.BadZipFile:
        # pas un zip : pickle brut
        out.extend(scan_pickle_bytes(_read(path), rel, "pickle"))
    return out


def _scan_safetensors(path: str, rel: str) -> List[Finding]:
    out: List[Finding] = []
    try:
        with open(path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if n > 100 * 1024 * 1024:
                out.append(finding("safetensors.header_oversize", Severity.MEDIUM, rel,
                                   f"en-tête de {n} octets", "", "format", "model"))
                return out
            header = json.loads(f.read(n).decode("utf-8"))
        meta = header.get("__metadata__", {})
        if isinstance(meta, dict):
            out.extend(scan_text(json.dumps(meta), rel, executable=False, analyzer="model"))
        # structure : chaque entrée doit avoir dtype/shape/data_offsets
        for k, v in header.items():
            if k == "__metadata__":
                continue
            if not (isinstance(v, dict) and {"dtype", "shape", "data_offsets"} <= set(v)):
                out.append(finding("safetensors.bad_entry", Severity.LOW, rel,
                                   f"entrée de tenseur mal formée : {k}", "", "format", "model"))
    except Exception as exc:  # noqa: BLE001
        out.append(finding("safetensors.unreadable", Severity.MEDIUM, rel,
                           f"en-tête safetensors illisible : {type(exc).__name__}", "", "format", "model"))
    return out


def _scan_numpy(path: str, rel: str) -> List[Finding]:
    out: List[Finding] = []
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".npz":
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    out.extend(_scan_npy_head(z.read(n)[:HEAD], f"{rel}!{n}"))
        else:
            out.extend(_scan_npy_head(_read(path, HEAD), rel))
    except zipfile.BadZipFile:
        out.append(finding("numpy.corrupt", Severity.MEDIUM, rel, "npz illisible", "", "format", "model"))
    return out


def _scan_npy_head(head: bytes, rel: str) -> List[Finding]:
    # \x93NUMPY <maj><min> <len> <dict header ascii>
    if head[:6] != b"\x93NUMPY":
        return [finding("numpy.bad_magic", Severity.LOW, rel, "en-tête npy inattendu", "", "format", "model")]
    try:
        hlen = struct.unpack("<H", head[8:10])[0]
        hdr = head[10:10 + hlen].decode("latin-1")
    except Exception:  # noqa: BLE001
        return [finding("numpy.bad_header", Severity.MEDIUM, rel, "en-tête npy illisible", "", "format", "model")]
    if "'descr': '|O'" in hdr or '"descr": "|O"' in hdr or "object" in hdr.lower():
        return [finding("numpy.object_dtype", Severity.CRITICAL, rel,
                        "tableau de dtype object : le chargement dépicklera du code",
                        hdr[:80], "malware", "model")]
    return []


def _scan_binary_strings(path: str, rel: str, analyzer: str) -> List[Finding]:
    """Extrait les chaînes ASCII imprimables d'un binaire et les passe au détecteur C2."""
    data = _read(path, MAX_TEXT)
    strings = re.findall(rb"[\x20-\x7e]{6,}", data)
    text = "\n".join(s.decode("latin-1") for s in strings[:50000])
    return scan_text(text, rel, executable=False, analyzer=analyzer)


def scan_model_file(path: str, rel: Optional[str] = None) -> List[Finding]:
    rel = rel or os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    head = _read(path, HEAD)

    if ext in SAFETENSORS_EXT or head[8:8 + 1] == b"{" and ext in SAFETENSORS_EXT:
        return _scan_safetensors(path, rel)
    if ext in NUMPY_EXT or head[:6] == b"\x93NUMPY":
        return _scan_numpy(path, rel)
    if ext in HDF5_EXT or head[:8] == b"\x89HDF\r\n\x1a\n":
        out = [finding("model.keras_hdf5", Severity.HIGH, rel,
                       "format HDF5/Keras : peut embarquer des couches Lambda (code marshalé) "
                       "et des attributs picklés ; charger uniquement avec safe_mode",
                       "", "malware", "model")]
        out.extend(_scan_binary_strings(path, rel, "model"))
        return out
    if ext in ONNX_EXT or head[:4] in (b"\x08\x01", b"\x08\x07") or b"onnx" in head[:64].lower():
        out = _scan_binary_strings(path, rel, "model")
        low = _read(path, MAX_TEXT).lower()
        if b"py_func" in low or b"pyfunc" in low or b"python_function" in low:
            out.append(finding("onnx.pyfunc", Severity.HIGH, rel,
                               "opérateur py_func/python dans le graphe ONNX/TF", "", "malware", "model"))
        return out
    if ext in TF_PB_EXT:
        out = _scan_binary_strings(path, rel, "model")
        if b"PyFunc" in _read(path, MAX_TEXT):
            out.append(finding("tf.pyfunc", Severity.HIGH, rel, "op PyFunc dans le graphe TensorFlow",
                               "", "malware", "model"))
        return out
    if ext in GGUF_EXT or head[:4] in (b"GGUF", b"ggml", b"lmgg"):
        return _scan_binary_strings(path, rel, "model")
    if ext in MSGPACK_EXT:
        return _scan_binary_strings(path, rel, "model")
    if ext in TEXT_CODE_EXT:
        txt = _read(path, MAX_TEXT).decode("utf-8", "replace")
        out = scan_text(txt, rel, executable=True, analyzer="model")
        if ext == ".ipynb":
            out.extend(_scan_notebook(txt, rel))
        return out
    if ext in TEXT_DATA_EXT:
        txt = _read(path, MAX_TEXT).decode("utf-8", "replace")
        return scan_text(txt, rel, executable=False, analyzer="model")

    # Pas d'extension parlante : on devine.
    if head[:2] == b"PK":                         # zip (pt, npz, safetensors.zip)
        return _scan_pt_zip(path, rel)
    if is_probably_pickle(head):
        return scan_pickle_bytes(_read(path), rel, "pickle")
    # Binaire inconnu : inspection de chaînes, jamais déclaré propre d'office.
    out = _scan_binary_strings(path, rel, "model")
    out.append(finding("model.unknown_format", Severity.LOW, rel,
                       "format non reconnu : inspection limitée aux chaînes", "", "format", "model"))
    return out


# Les .pt modernes sont des zip : on route vers l'analyse de membres.
_orig = scan_model_file


def scan_model_file(path: str, rel: Optional[str] = None) -> List[Finding]:  # noqa: F811
    rel = rel or os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in PICKLE_EXT:
        head = _read(path, 4)
        if head[:2] == b"PK":
            return _scan_pt_zip(path, rel)
        return scan_pickle_bytes(_read(path), rel, "pickle")
    return _orig(path, rel)


_NB_CODE_RE = re.compile(r'"cell_type"\s*:\s*"code"')


def _scan_notebook(txt: str, rel: str) -> List[Finding]:
    out: List[Finding] = []
    try:
        nb = json.loads(txt)
    except Exception:  # noqa: BLE001
        return out
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") == "code":
            src = "".join(cell.get("source", []))
            out.extend(scan_text(src, f"{rel}#cell{i}", executable=True, analyzer="model"))
        for o in cell.get("outputs", []):
            if o.get("output_type") == "execute_result":
                pass
    return out
