"""nexus_unified.security.archive_scan — inspection d'archives AVANT extraction.

Un modèle ou un jeu de données arrive souvent en .zip, .tar, .tar.gz. On ne
l'extrait jamais tel quel : on lit d'abord la table des matières et on refuse

- la traversée de chemin (``../`` ou chemin absolu : écrit hors du dossier cible) ;
- les liens symboliques et les liens durs (pointent hors du bac, classique de
  l'évasion de sandbox) ;
- les fichiers de périphérique / FIFO dans un tar ;
- les bombes de décompression (ratio compressé→décompressé démesuré, ou
  taille totale au-delà d'un plafond).

L'extraction sûre (`safe_extract`) applique ces mêmes règles au moment d'écrire.
"""
from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from .findings import Finding, Severity, finding

MAX_TOTAL_UNCOMPRESSED = 50 * 1024 ** 3   # 50 Gio
MAX_RATIO = 200                           # décompressé / compressé
MAX_ENTRIES = 500_000


def _is_unsafe_path(name: str) -> bool:
    if not name:
        return False
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or name.startswith(("/", "\\")):
        return True
    if len(name) >= 2 and name[1] == ":":   # C:\ Windows
        return True
    parts = p.parts
    return ".." in parts


def inspect_zip(path: str, rel: str) -> List[Finding]:
    out: List[Finding] = []
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_ENTRIES:
                out.append(finding("archive.too_many_entries", Severity.HIGH, rel,
                                   f"{len(infos)} entrées", "", "dos", "archive"))
            total_unc = 0
            total_comp = 0
            for i in infos:
                if _is_unsafe_path(i.filename):
                    out.append(finding("archive.path_traversal", Severity.CRITICAL, rel,
                                       "entrée hors du dossier cible", i.filename, "malware", "archive"))
                # bit 0x4 des attributs externes Unix = type de fichier ; S_IFLNK = 0xA000
                mode = (i.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    out.append(finding("archive.symlink", Severity.HIGH, rel,
                                       "lien symbolique dans l'archive", i.filename, "malware", "archive"))
                total_unc += i.file_size
                total_comp += i.compress_size
                if i.compress_size > 0 and i.file_size / max(i.compress_size, 1) > MAX_RATIO * 5:
                    out.append(finding("archive.zip_bomb_entry", Severity.HIGH, rel,
                                       f"entrée au ratio {i.file_size // max(i.compress_size,1)}:1",
                                       i.filename, "dos", "archive"))
            if total_unc > MAX_TOTAL_UNCOMPRESSED:
                out.append(finding("archive.oversize", Severity.HIGH, rel,
                                   f"{total_unc // 1024**3} Gio décompressés", "", "dos", "archive"))
            if total_comp > 0 and total_unc / total_comp > MAX_RATIO:
                out.append(finding("archive.zip_bomb", Severity.HIGH, rel,
                                   f"ratio global {total_unc // total_comp}:1", "", "dos", "archive"))
    except zipfile.BadZipFile as exc:
        out.append(finding("archive.corrupt", Severity.MEDIUM, rel, "zip illisible",
                           str(exc)[:120], "format", "archive"))
    return out


def inspect_tar(path: str, rel: str) -> List[Finding]:
    out: List[Finding] = []
    try:
        with tarfile.open(path) as t:
            total = 0
            n = 0
            for m in t:
                n += 1
                if n > MAX_ENTRIES:
                    out.append(finding("archive.too_many_entries", Severity.HIGH, rel,
                                       "trop d'entrées", "", "dos", "archive"))
                    break
                if _is_unsafe_path(m.name):
                    out.append(finding("archive.path_traversal", Severity.CRITICAL, rel,
                                       "entrée hors du dossier cible", m.name, "malware", "archive"))
                if m.issym() or m.islnk():
                    tgt = m.linkname
                    sev = Severity.CRITICAL if _is_unsafe_path(tgt) else Severity.HIGH
                    out.append(finding("archive.link", sev, rel,
                                       f"lien ({'sym' if m.issym() else 'dur'}) → {tgt}",
                                       m.name, "malware", "archive"))
                if m.ischr() or m.isblk() or m.isfifo() or m.isdev():
                    out.append(finding("archive.device_node", Severity.HIGH, rel,
                                       "nœud de périphérique dans l'archive", m.name, "malware", "archive"))
                total += max(m.size, 0)
            if total > MAX_TOTAL_UNCOMPRESSED:
                out.append(finding("archive.oversize", Severity.HIGH, rel,
                                   f"{total // 1024**3} Gio décompressés", "", "dos", "archive"))
    except tarfile.TarError as exc:
        out.append(finding("archive.corrupt", Severity.MEDIUM, rel, "tar illisible",
                           str(exc)[:120], "format", "archive"))
    return out


def inspect_archive(path: str, rel: str) -> List[Finding]:
    if zipfile.is_zipfile(path):
        return inspect_zip(path, rel)
    if tarfile.is_tarfile(path):
        return inspect_tar(path, rel)
    return [finding("archive.unknown", Severity.LOW, rel,
                    "archive présumée mais format non reconnu", "", "format", "archive")]


def safe_extract(path: str, dest: str) -> Tuple[List[str], List[Finding]]:
    """Extrait sous `dest` en refusant toute entrée dangereuse. Retourne
    (fichiers extraits, constats). Rien n'est écrit hors de `dest`."""
    findings = inspect_archive(path, os.path.basename(path))
    if any(f.severity.rank >= Severity.HIGH.rank for f in findings):
        return [], findings
    dest = os.path.realpath(dest)
    os.makedirs(dest, exist_ok=True)
    extracted: List[str] = []

    def _safe_target(name: str) -> Optional[str]:
        if _is_unsafe_path(name):
            return None
        target = os.path.realpath(os.path.join(dest, name))
        if target != dest and not target.startswith(dest + os.sep):
            return None
        return target

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if ((i.external_attr >> 16) & 0o170000) == 0o120000:
                    continue  # on saute les liens
                t = _safe_target(i.filename)
                if t is None:
                    findings.append(finding("archive.blocked_entry", Severity.HIGH,
                                           os.path.basename(path), "entrée bloquée à l'extraction",
                                           i.filename, "malware", "archive"))
                    continue
                if i.is_dir():
                    os.makedirs(t, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(t), exist_ok=True)
                    with z.open(i) as src, open(t, "wb") as dst:
                        _copy_capped(src, dst)
                    extracted.append(t)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as tf:
            for m in tf:
                if m.issym() or m.islnk() or m.isdev():
                    continue
                t = _safe_target(m.name)
                if t is None:
                    findings.append(finding("archive.blocked_entry", Severity.HIGH,
                                           os.path.basename(path), "entrée bloquée à l'extraction",
                                           m.name, "malware", "archive"))
                    continue
                if m.isdir():
                    os.makedirs(t, exist_ok=True)
                elif m.isfile():
                    os.makedirs(os.path.dirname(t), exist_ok=True)
                    src = tf.extractfile(m)
                    if src is not None:
                        with open(t, "wb") as dst:
                            _copy_capped(src, dst)
                        extracted.append(t)
    return extracted, findings


def _copy_capped(src, dst, cap: int = MAX_TOTAL_UNCOMPRESSED) -> None:
    written = 0
    while True:
        chunk = src.read(1 << 20)
        if not chunk:
            break
        written += len(chunk)
        if written > cap:
            raise ValueError("extraction au-delà du plafond (bombe de décompression)")
        dst.write(chunk)
