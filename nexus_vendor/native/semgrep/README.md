# Semgrep SAST (Python CLI)
**Source :** semgrep.zip → semgrep-develop/cli/src/semgrep/
**Language :** Python 3.11+ (CLI) + OCaml (core — non extrait car binaire compilé)
**Installation :** `pip install semgrep` (inclut le binaire semgrep-core OCaml)

## Structure extraite

| Module Python | Rôle |
|---------------|------|
| `python/semgrep/main.py` | Point d'entrée CLI, `main()`, `conditional_welcome()` |
| `python/semgrep/rule.py` | `class Rule` — représente une règle SAST |
| `python/semgrep/rule_match.py` | `class RuleMatch`, `class RuleMatches` — findings |
| `python/semgrep/output.py` | `class OutputHandler`, `class OutputSettings` — formatage JSON/SARIF |
| `python/semgrep/error.py` | Exceptions typées : `SemgrepError`, `ParseError`, `MatchingError` |
| `python/semgrep/semgrep_core.py` | Bridge Python → binaire OCaml `semgrep-core` |
| `python/semgrep/config_resolver.py` | Résolution des configs `p/python`, `auto`, etc. |
| `python/semgrep/target_manager.py` | Gestion des fichiers cibles (glob, exclusions, gitignore) |

## Fonctions clés

```python
# rule.py
class Rule:
    @classmethod
    def from_json(cls, json_obj: dict) -> "Rule": ...
    @property
    def id(self) -> str: ...
    @property
    def message(self) -> str: ...
    @property
    def severity(self) -> str: ...         # "ERROR"|"WARNING"|"INFO"
    @property
    def languages(self) -> list[str]: ...
    @property
    def pattern(self) -> str: ...
    @property
    def fix(self) -> str | None: ...

# rule_match.py
class RuleMatch:
    rule_id: str
    path: Path
    start: Position          # .line, .col
    end: Position
    message: str
    severity: str
    fix: str | None
    match_based_id: str      # hash déterministe pour déduplication

# output.py
class OutputHandler:
    def handle_semgrep_core_return(self, core_runner_output): ...
    def output(self, rules, rule_matches, semgrep_errors): ...
```

## Note sur semgrep-core (OCaml)
Le moteur de matching AST est compilé en binaire OCaml.
Source disponible sur https://github.com/semgrep/semgrep (dossier `src/`)
mais non inclus ici car il nécessite une toolchain OCaml+opam pour compiler.
