"""
tests.test_brain_registry
============================

Mission 2 (Meta Framework / Nexus Studio) — livrable D3, test requis en §4 :
« le registre statique (D3) référence des identifiants réellement présents
dans nexus_brain/ et nexus_functor/ (pas de faux positifs) ».

Ne dépend PAS de nexus_compose : les deux dépôts n'ont aucun lien Python
croisé (cf. nexus_brain/registry.py et Nexus_Assistant/docs/registry_schema.md
— « sans import croisé »). Le contrat de forme attendu (les clés NodeMeta)
est donc recopié ici en dur plutôt qu'importé — ce qui a pour bénéfice
supplémentaire de prouver que ce registre respecte la forme documentée sans
jamais avoir vu le code qui la définit dans l'autre dépôt.
"""

import _pathfix  # noqa: F401
import importlib
import re
import unittest
from pathlib import Path

from nexus_brain.registry import BRAIN_NODES, get_node, list_nodes

# Contrat NodeMeta (cf. Nexus_Assistant/docs/registry_schema.md, §1) —
# recopié en dur, volontairement, pour ne PAS importer nexus_compose ici.
_EXPECTED_NODEMETA_FIELDS = {
    "id", "module", "module_name", "function", "description", "tag",
    "phase", "type", "io_in", "io_out", "ref", "repo", "virtual",
    "subsection", "capabilities",
}

_NEXUS_BRAIN_ROOT = Path(__file__).resolve().parent.parent  # .../Nexus_Brain


class TestBrainRegistryShape(unittest.TestCase):
    """Le registre respecte le contrat D1 — un dict par nœud, exactement
    les champs NodeMeta, sans en inventer ni en oublier."""

    def test_registry_is_non_empty(self):
        self.assertGreater(len(BRAIN_NODES), 0)

    def test_every_entry_has_exactly_the_nodemeta_fields(self):
        for node in BRAIN_NODES:
            with self.subTest(node_id=node.get("id")):
                self.assertEqual(set(node.keys()), _EXPECTED_NODEMETA_FIELDS)

    def test_every_entry_has_phase_brain(self):
        """Niveau 1 est hors pipeline nexus_compose — cf.
        docs/registry_schema.md §2.2 : "brain" est la seule phase ajoutée
        par cette mission, réservée aux composants cognitifs Niveau 1."""
        for node in BRAIN_NODES:
            with self.subTest(node_id=node.get("id")):
                self.assertEqual(node["phase"], "brain")

    def test_ids_are_unique(self):
        ids = [node["id"] for node in BRAIN_NODES]
        self.assertEqual(len(ids), len(set(ids)), f"Identifiants dupliqués : {ids}")

    def test_ids_start_with_their_declared_module(self):
        for node in BRAIN_NODES:
            with self.subTest(node_id=node["id"]):
                self.assertTrue(
                    node["id"].startswith(node["module"] + "."),
                    f"{node['id']!r} devrait commencer par {node['module']!r}.",
                )

    def test_repo_field_never_invents_an_external_org(self):
        """cf. docs/registry_schema.md §3.3 : `repo` doit pointer vers ce
        monorepo (Nexus_Brain/...), jamais vers un org GitHub externe
        inventé — ces composants sont natifs, pas des forks."""
        for node in BRAIN_NODES:
            with self.subTest(node_id=node["id"]):
                self.assertTrue(node["repo"].startswith("Nexus_Brain/"))


class TestBrainRegistryReferencesRealCode(unittest.TestCase):
    """Le test anti-faux-positifs proprement dit : chaque `ref` pointe vers
    un fichier qui existe réellement sur disque, et chaque nom de classe
    cité dans `function` est un attribut réel de ce module une fois importé
    — pas une chaîne plausible mais inventée."""

    @staticmethod
    def _ref_to_module(ref: str) -> str:
        # nexus_functor/nexus_functor/xxx.py : le paquet réellement installé
        # (cf. nexus_functor/pyproject.toml) est le nexus_functor
        # INTÉRIEUR — ne garder que ce dernier segment de dépôt avant de
        # convertir en chemin de module.
        if ref.startswith("nexus_functor/nexus_functor/"):
            ref = ref[len("nexus_functor/"):]
        assert ref.startswith(("nexus_brain/", "nexus_functor/")), (
            f"ref {ref!r} ne pointe ni dans nexus_brain/ ni dans nexus_functor/"
        )
        assert ref.endswith(".py"), ref
        return ref[:-len(".py")].replace("/", ".")

    @staticmethod
    def _class_names_in(function_field: str) -> list:
        # Tokens PascalCase (NexusCore, F0MacroStrategySelector, ...) —
        # extraction généreuse plutôt que stricte : un nom qui n'existe pas
        # vraiment dans le module importé fait échouer le test ci-dessous,
        # c'est le but.
        return sorted(set(re.findall(r"\b[A-Z][A-Za-z0-9]*\b", function_field)))

    def test_ref_file_exists_on_disk_for_every_node(self):
        for node in BRAIN_NODES:
            with self.subTest(node_id=node["id"]):
                path = _NEXUS_BRAIN_ROOT / node["ref"]
                self.assertTrue(
                    path.is_file(),
                    f"{node['id']}: ref {node['ref']!r} introuvable sur disque ({path})",
                )

    def test_function_class_names_are_real_attributes_of_the_ref_module(self):
        for node in BRAIN_NODES:
            with self.subTest(node_id=node["id"]):
                module_path = self._ref_to_module(node["ref"])
                module = importlib.import_module(module_path)

                class_names = self._class_names_in(node["function"])
                self.assertGreater(
                    len(class_names), 0,
                    f"{node['id']}: aucun nom de classe PascalCase trouvé "
                    f"dans function={node['function']!r}",
                )
                for name in class_names:
                    self.assertTrue(
                        hasattr(module, name),
                        f"{node['id']}: {module_path}.{name} n'existe pas — "
                        f"le champ function référence quelque chose d'absent du code réel",
                    )


class TestBrainRegistryAccessors(unittest.TestCase):

    def test_list_nodes_returns_a_defensive_copy(self):
        nodes = list_nodes()
        nodes.append({"tampered": True})
        self.assertEqual(len(list_nodes()), len(BRAIN_NODES))

    def test_get_node_finds_known_id(self):
        node = get_node("core.brain")
        self.assertIsNotNone(node)
        self.assertEqual(node["ref"], "nexus_brain/core/brain.py")

    def test_get_node_returns_none_for_unknown_id(self):
        self.assertIsNone(get_node("does.not.exist"))

    def test_get_node_result_is_also_a_defensive_copy(self):
        node = get_node("core.brain")
        node["id"] = "tampered"
        self.assertEqual(get_node("core.brain")["id"], "core.brain")


if __name__ == "__main__":
    unittest.main()
