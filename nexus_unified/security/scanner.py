"""nexus_unified.security.scanner — passerelle d'inspection obligatoire d'un artefact.

`ArtifactScanner.scan(path)` parcourt un fichier ou un dossier (modèle,
dataset, dépôt de code téléchargé), calcule l'empreinte SHA-256 de chaque
fichier, lance les analyseurs internes (archives, formats de modèle, C2) et,
s'ils sont installés, les analyseurs externes (ClamAV `clamscan`, règles YARA).
Il retourne un `ScanReport` dont le `verdict` décide de la suite.

Aucun artefact n'échappe à cette passerelle : le point d'entrée réseau de
tout téléchargement (modèle, dataset, poids) passe par ici avant que le code
agent ne puisse y toucher — voir `gate.inspect_and_admit`.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set

from .archive_scan import inspect_archive
from .findings import Finding, ScanReport, Severity, finding
from .model_scan import scan_model_file

ARCHIVE_EXT = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar.gz"}
SKIP_DIRS = {".git", "__pycache__", ".cache", "node_modules"}
MAX_FILE = 25 * 1024 ** 3        # au-delà, on ne lit que l'en-tête
MAX_FILES = 200_000


@dataclass
class ScannerConfig:
    use_clamav: bool = True          # si `clamscan` présent
    use_yara: bool = True            # si module `yara` + règles présents
    yara_rules: Optional[str] = None  # chemin d'un fichier de règles compilées ou source
    follow_symlinks: bool = False
    max_file_bytes: int = MAX_FILE


def sha256_file(path: str, cap: int = MAX_FILE) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            read += len(chunk)
            h.update(chunk)
            if read >= cap:
                h.update(b"<truncated>")
                break
    return h.hexdigest()


class ArtifactScanner:
    def __init__(self, config: Optional[ScannerConfig] = None) -> None:
        self.cfg = config or ScannerConfig()
        self._clamav = shutil.which("clamscan") if self.cfg.use_clamav else None
        self._yara = self._load_yara() if self.cfg.use_yara else None

    def _load_yara(self):
        try:
            import yara  # type: ignore
        except Exception:
            return None
        rules = self.cfg.yara_rules
        try:
            if rules and os.path.isfile(rules):
                return yara.compile(filepath=rules)
            return None
        except Exception:
            return None

    # ── API ────────────────────────────────────────────────────────────────
    def scan(self, path: str, artifact_name: Optional[str] = None) -> ScanReport:
        path = os.path.abspath(path)
        report = ScanReport(artifact=artifact_name or os.path.basename(path.rstrip("/")))
        report.analyzers_run = ["archive", "model", "ioc", "pickle"]
        if self._clamav:
            report.analyzers_run.append("clamav")
        else:
            report.analyzers_unavailable["clamav"] = "clamscan introuvable (apt install clamav)"
        if self._yara:
            report.analyzers_run.append("yara")
        else:
            report.analyzers_unavailable["yara"] = "module yara ou règles absents"

        files = self._iter_files(path, report)
        for abspath, rel in files:
            self._scan_one(abspath, rel, report)
        if self._clamav:
            report.add(self._run_clamav(path))
        return report

    # ── interne ──────────────────────────────────────────────────────────
    def _iter_files(self, path: str, report: ScanReport):
        out = []
        if os.path.isfile(path):
            out.append((path, os.path.basename(path)))
            return out
        base = path
        n = 0
        for root, dirs, names in os.walk(path, followlinks=self.cfg.follow_symlinks):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in names:
                ap = os.path.join(root, name)
                if os.path.islink(ap) and not self.cfg.follow_symlinks:
                    report.add([finding("fs.symlink", Severity.MEDIUM,
                                       os.path.relpath(ap, base), "lien symbolique dans l'artefact",
                                       os.readlink(ap), "malware", "scanner")])
                    continue
                out.append((ap, os.path.relpath(ap, base)))
                n += 1
                if n >= MAX_FILES:
                    report.errors.append(f"plus de {MAX_FILES} fichiers : inspection interrompue")
                    return out
        return out

    def _scan_one(self, abspath: str, rel: str, report: ScanReport) -> None:
        try:
            size = os.path.getsize(abspath)
        except OSError as exc:
            report.errors.append(f"{rel}: {exc}")
            return
        report.files_scanned += 1
        report.bytes_scanned += size
        try:
            report.sha256[rel] = sha256_file(abspath, self.cfg.max_file_bytes)
        except OSError as exc:
            report.errors.append(f"{rel}: empreinte impossible ({exc})")
            return

        ext = os.path.splitext(rel)[1].lower()
        name_l = rel.lower()
        try:
            if ext in ARCHIVE_EXT or name_l.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
                report.add(inspect_archive(abspath, rel))
            else:
                report.add(scan_model_file(abspath, rel))
            if self._yara:
                report.add(self._run_yara(abspath, rel))
        except Exception as exc:  # noqa: BLE001 — un analyseur qui jette = constat, jamais un silence
            report.errors.append(f"{rel}: analyse interrompue ({type(exc).__name__}: {exc})")

    def _run_yara(self, abspath: str, rel: str) -> List[Finding]:
        out: List[Finding] = []
        try:
            for m in self._yara.match(abspath):
                tags = ",".join(m.tags)
                out.append(finding(f"yara.{m.rule}", Severity.HIGH, rel,
                                   f"règle YARA {m.rule} ({tags})", "", "malware", "yara"))
        except Exception:
            pass
        return out

    def _run_clamav(self, path: str) -> List[Finding]:
        out: List[Finding] = []
        try:
            r = subprocess.run([self._clamav, "-r", "--no-summary", "--stdout", path],
                               capture_output=True, text=True, timeout=1800)
            for line in r.stdout.splitlines():
                if line.endswith("FOUND"):
                    fpath, _, sig = line.rpartition(":")
                    out.append(finding("clamav.signature", Severity.CRITICAL,
                                       os.path.relpath(fpath.strip(), path) if os.path.isabs(fpath) else fpath,
                                       f"signature ClamAV : {sig.replace(' FOUND','').strip()}",
                                       "", "malware", "clamav"))
        except subprocess.TimeoutExpired:
            out.append(finding("clamav.timeout", Severity.MEDIUM, path,
                               "clamscan a dépassé le délai", "", "policy", "clamav"))
        except Exception:
            pass
        return out
