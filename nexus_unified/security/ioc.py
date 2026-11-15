"""nexus_unified.security.ioc — indicateurs de commande et contrôle (C2) et d'exfiltration.

Appliqué à tout texte extrait d'un artefact (code, métadonnées de modèle,
gabarits de chat, notebooks, scripts, chaînes d'un pickle). Les règles sont
défensives : elles signalent, elles ne contactent jamais l'indicateur.

Gradation retenue :
- CRITICAL : chaîne caractéristique d'un framework C2 ou d'un shell inversé ;
- HIGH     : point d'exfiltration connu (webhook, bot, tunnel), IP littérale
             publique dans du code exécutable, commande téléchargée-exécutée ;
- MEDIUM   : URL ou domaine inconnu dans un artefact qui ne devrait pas en
             contenir (poids, données), domaine dynamique ;
- INFO     : URL d'hôte de confiance (documentation, dépôt d'origine).
"""
from __future__ import annotations

import ipaddress
import math
import re
from collections import Counter
from typing import Iterable, List, Sequence, Set

from .findings import Finding, Severity, finding

# ── Signatures de frameworks C2, implants et shells inversés ─────────────────
C2_SIGNATURES: Sequence[tuple] = (
    # (regex, détail)
    (r"ReflectiveLoader", "chargeur réflexif (Cobalt Strike, Metasploit)"),
    (r"beacon(?:_x64)?\.dll|\bbeacon\.(?:exe|bin)\b", "charge Cobalt Strike Beacon"),
    (r"%COMSPEC%", "appel d'interpréteur Windows typique d'implant"),
    (r"\bmeterpreter\b|\bmetsrv\b|stdapi_sys_process", "charge Meterpreter"),
    (r"\bsliver(?:-client|-server|_implant)\b|bishopfox/sliver", "implant Sliver"),
    (r"\bmythic(?:_payload|-cli)\b|its-a-feature/Mythic", "agent Mythic"),
    (r"\bEmpire(?:Stager|Agent)\b|powershell[\s-]+empire", "agent PowerShell Empire"),
    (r"\bHavoc(?:Demon)?\b.{0,40}demon", "implant Havoc"),
    (r"\bbrute_?ratel\b|\bbadger\.(?:exe|dll)\b", "implant Brute Ratel"),
    (r"powershell(?:\.exe)?\s+(?:-\w+\s+)*-e(?:nc(?:odedcommand)?)?\s+[A-Za-z0-9+/=]{20,}",
     "PowerShell encodé"),
    (r"IEX\s*\(\s*New-Object\s+Net\.WebClient", "téléchargement-exécution PowerShell"),
    (r"Invoke-(?:Expression|Shellcode|Mimikatz|ReflectivePEInjection)", "cmdlet offensive"),
    (r"/dev/tcp/\d{1,3}(?:\.\d{1,3}){3}/\d+", "shell inversé bash /dev/tcp"),
    (r"bash\s+-i\s*>&\s*/dev/tcp/", "shell inversé bash"),
    (r"\bnc(?:at)?\s+(?:-\w+\s+)*-e\s+/bin/(?:ba)?sh", "shell inversé netcat"),
    (r"mkfifo\s+/tmp/\w+.{0,40}\bnc\b", "shell inversé fifo + netcat"),
    (r"socat\s+(?:tcp|openssl)[^\n]{0,80}exec:", "shell inversé socat"),
    (r"pty\.spawn\(\s*['\"]/bin/(?:ba)?sh", "shell interactif python pty"),
    (r"os\.dup2\([^)]*fileno\(\)[^)]*\)", "redirection de descripteurs (shell inversé)"),
    (r"\bxmrig\b|stratum\+tcp://|\bcryptonight\b", "mineur de cryptomonnaie"),
)

# ── Points d'exfiltration et de tunnel connus ────────────────────────────────
EXFIL_PATTERNS: Sequence[tuple] = (
    (r"discord(?:app)?\.com/api/webhooks/\d+", "webhook Discord"),
    (r"api\.telegram\.org/bot\d+:[\w-]+", "bot Telegram"),
    (r"hooks\.slack\.com/services/", "webhook Slack"),
    (r"\b[\w-]+\.ngrok(?:-free)?\.(?:io|app|dev)\b", "tunnel ngrok"),
    (r"\b[\w-]+\.trycloudflare\.com\b", "tunnel Cloudflare"),
    (r"\bserveo\.net\b|\blocalhost\.run\b|\bpinggy\.io\b", "tunnel SSH public"),
    (r"\bpastebin\.com/raw/|\bpaste\.ee/r/|\bhastebin\.com/raw/", "charge sur site de collage"),
    (r"\btransfer\.sh/|\bfile\.io/|\b0x0\.st\b|\btemp\.sh/", "dépôt de fichiers éphémère"),
    (r"\bwebhook\.site/|\brequestbin\.|\bpipedream\.net\b|\bbeeceptor\.com\b", "collecteur de requêtes"),
    (r"\b[\w-]+\.(?:oast\.(?:fun|live|site|online|pro|me)|interact\.sh|burpcollaborator\.net|dnslog\.cn)\b",
     "collecteur hors bande (OAST)"),
)
DYNAMIC_DNS_SUFFIXES = (
    ".duckdns.org", ".no-ip.org", ".no-ip.com", ".ddns.net", ".hopto.org",
    ".zapto.org", ".dyndns.org", ".freedns.afraid.org", ".mooo.com", ".servegame.com",
)
ONION_RE = re.compile(r"\b[a-z2-7]{16,56}\.onion\b")
# Hôte DNS dynamique nu, sans schéma (socket.connect(('x.duckdns.org', 4444)))
DYNDNS_RE = re.compile(
    r"\b[\w-]+\.(?:duckdns\.org|no-ip\.(?:org|com)|ddns\.net|hopto\.org|zapto\.org"
    r"|dyndns\.org|afraid\.org|mooo\.com|servegame\.com)\b", re.I)

URL_RE = re.compile(r"\b(?:https?|ftp|wss?|tcp|udp)://[^\s'\"<>()\[\]{}\\]{3,300}", re.I)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
HOST_RE = re.compile(r"^(?:[a-z]+://)?(?:[^@/]*@)?([^:/?#]+)", re.I)

# Hôtes considérés comme de confiance dans des métadonnées (documentation,
# dépôts d'origine). La présence d'une URL de ces hôtes reste INFO.
DEFAULT_TRUSTED_HOSTS: Set[str] = {
    "huggingface.co", "github.com", "raw.githubusercontent.com", "arxiv.org",
    "pytorch.org", "pypi.org", "files.pythonhosted.org", "readthedocs.io",
    "creativecommons.org", "opensource.org", "apache.org", "www.apache.org",
    "spdx.org", "doi.org", "schema.org", "w3.org", "www.w3.org", "json-schema.org",
}

_C2_RES = [(re.compile(p, re.I), d) for p, d in C2_SIGNATURES]
_EXFIL_RES = [(re.compile(p, re.I), d) for p, d in EXFIL_PATTERNS]


def _host_of(url: str) -> str:
    m = HOST_RE.match(url.strip())
    return (m.group(1) if m else "").lower().strip(".")


def _is_trusted(host: str, trusted: Set[str]) -> bool:
    return any(host == t or host.endswith("." + t) for t in trusted)


def _public_ipv4(s: str) -> bool:
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return False
    if any(int(o) > 255 for o in s.split(".")):
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


def _looks_like_version(s: str, text: str, start: int) -> bool:
    """1.2.3.4 précédé de 'version'/'v' = numéro de version, pas une IP."""
    ctx = text[max(0, start - 20):start].lower().rstrip(" \t'\"=:([")
    return ctx.endswith(("version", "ver", "v", "release", "rev", "tag"))


def shannon_entropy(data: str) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


B64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def scan_text(text: str, file: str, *, executable: bool,
              trusted_hosts: Set[str] = frozenset(DEFAULT_TRUSTED_HOSTS),
              analyzer: str = "ioc", max_findings: int = 50) -> List[Finding]:
    """Cherche des indicateurs C2 et d'exfiltration dans un texte.

    executable : True si le texte est du code qui s'exécutera (script,
    code distant, gabarit). Une IP publique littérale y est HIGH ; dans
    des métadonnées de données elle reste MEDIUM.
    """
    out: List[Finding] = []
    if not text:
        return out
    for rx, detail in _C2_RES:
        m = rx.search(text)
        if m:
            out.append(finding("c2.signature", Severity.CRITICAL, file, detail,
                               m.group(0), "c2", analyzer))
    for rx, detail in _EXFIL_RES:
        m = rx.search(text)
        if m:
            out.append(finding("c2.exfil_endpoint", Severity.HIGH, file,
                               f"point d'exfiltration : {detail}", m.group(0), "c2", analyzer))
    m = ONION_RE.search(text)
    if m:
        out.append(finding("c2.onion", Severity.HIGH, file, "adresse .onion", m.group(0), "c2", analyzer))
    m = DYNDNS_RE.search(text)
    if m and not any(f.rule == "c2.dynamic_dns" for f in out):
        out.append(finding("c2.dynamic_dns", Severity.HIGH, file,
                           "domaine DNS dynamique", m.group(0), "c2", analyzer))

    seen_hosts: Set[str] = set()
    for m in URL_RE.finditer(text):
        url = m.group(0)
        host = _host_of(url)
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        if host.endswith(DYNAMIC_DNS_SUFFIXES):
            out.append(finding("c2.dynamic_dns", Severity.HIGH, file,
                               "domaine DNS dynamique", url, "c2", analyzer))
        elif _public_ipv4(host):
            out.append(finding("c2.ip_url", Severity.HIGH if executable else Severity.MEDIUM,
                               file, "URL vers une IP littérale", url, "c2", analyzer))
        elif _is_trusted(host, set(trusted_hosts)):
            out.append(finding("net.trusted_url", Severity.INFO, file,
                               "URL d'hôte de confiance", url, "c2", analyzer))
        elif executable:
            out.append(finding("net.unknown_url_in_code", Severity.MEDIUM, file,
                               "URL d'hôte inconnu dans du code exécutable", url, "c2", analyzer))
        else:
            out.append(finding("net.unknown_url", Severity.LOW, file,
                               "URL d'hôte inconnu", url, "c2", analyzer))
        if len(out) >= max_findings:
            return out

    if executable:
        for m in IPV4_RE.finditer(text):
            ip = m.group(0)
            if _public_ipv4(ip) and not _looks_like_version(ip, text, m.start()):
                out.append(finding("c2.ip_literal", Severity.HIGH, file,
                                   "IP publique littérale dans du code", ip, "c2", analyzer))
                break
        for m in B64_BLOB_RE.finditer(text):
            blob = m.group(0)
            if shannon_entropy(blob[:4096]) > 5.2:
                out.append(finding("obfuscation.b64_blob", Severity.MEDIUM, file,
                                   "bloc base64 à forte entropie dans du code",
                                   blob[:60], "malware", analyzer))
                break
    return out[:max_findings]
