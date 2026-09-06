import copy
import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import audit_skill_instructions as audit
from scripts import eval_skill_routing as evaluator


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/instruction-baseline.json"
POLICY = ROOT / "tests/fixtures/instruction-policy.json"
CASES = ROOT / "tests/fixtures/skill-routing.json"


class FrontmatterTests(unittest.TestCase):
    def test_real_yaml_scalars_and_optional_metadata(self):
        for scalar, expected in ((">-\n  First line\n  second line", "First line second line"),
                                 ("|-\n  First line\n  second line", "First line\nsecond line"),
                                 ('"A colon: and a Unicode \\u2713"', "A colon: and a Unicode \u2713"),
                                 ("'It''s quoted'", "It's quoted")):
            text = "---\nname: sample\ndescription: " + scalar + "\nmetadata:\n  key: value\n---\nBody"
            parsed = audit.frontmatter(text)
            self.assertEqual(parsed["description"], expected)
            self.assertEqual(parsed["metadata"], {"key": "value"})

    def test_rejects_ambiguous_or_non_string_frontmatter(self):
        for fields in ("name: one\nname: two\ndescription: text", "name: sample\ndescription: false",
                       "name: sample\ndescription: ''", "name: sample\ndescription: [one, two]"):
            with self.assertRaises(ValueError):
                audit.frontmatter("---\n" + fields + "\n---\n")

    def test_reference_graph_checks_transitive_links_but_not_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "SKILL.md"
            entry.write_text("[details](details.md)\n`[example](url)`\n```md\n[example](missing.md)\n```\n")
            (root / "details.md").write_text("[missing](absent.md)\n")
            refs, errors = audit.reference_graph(entry, root)
            self.assertEqual(refs, ["details.md"])
            self.assertEqual(len(errors), 1)
            self.assertIn("absent.md", errors[0])
            (root / "details.md").write_text("[outside](../outside.md)\n")
            self.assertIn("escapes repository", audit.reference_graph(entry, root)[1][0])
            (root / "details.md").write_text("Read `references/missing.md`.\n")
            self.assertIn("references/missing.md", audit.reference_graph(entry, root)[1][0])


class DiscoveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit.inventory(ROOT)

    def test_current_metadata_references_and_policy(self):
        errors, _ = audit.check(copy.deepcopy(self.report), json.loads(POLICY.read_text()))
        self.assertEqual(errors, [])

    def test_changed_invocation_and_unreviewed_length_fail(self):
        report = copy.deepcopy(self.report)
        ship = next(r for r in report["skills"] if r["name"] == "ship-toolbox")
        ship["implicit"] = True
        ship["description_chars"] = 241
        errors, warnings = audit.check(report, {"description_exceptions": {}})
        self.assertTrue(any("explicit-only" in e for e in errors))
        self.assertTrue(any("documented exception" in e for e in errors))
        self.assertTrue(warnings)
        report = copy.deepcopy(self.report)
        errors, _ = audit.check(report, {"description_exceptions": {"ship-toolbox": "old exception"}})
        self.assertTrue(any("stale" in e for e in errors))

    def test_preserved_imports_are_verbatim_and_reachable(self):
        original = {r["name"]: r for r in json.loads(BASELINE.read_text())["skills"]}
        for row in self.report["skills"]:
            entry = ROOT / row["path"]
            provenance = entry.parent / "references/provenance.json"
            if not provenance.exists():
                continue
            data = json.loads(provenance.read_text())
            upstream = entry.parent / data["preserved_file"]
            # Codex's documented registration entry is SKILL.md. Preserved
            # guidance must not introduce a second, even nested, entrypoint.
            self.assertEqual(list(entry.parent.rglob("SKILL.md")), [entry])
            self.assertNotEqual(upstream.name, "SKILL.md")
            self.assertEqual(audit.digest(upstream.read_bytes()), original[row["name"]]["sha256"])
            self.assertEqual(data["sha256"], original[row["name"]]["sha256"])
            self.assertIn(str(upstream.relative_to(ROOT)), row["references"])

    def test_wechat_moved_sections_keep_the_complete_original_contract(self):
        preservation = json.loads((ROOT / "tests/fixtures/instruction-preservation.json").read_text())
        entry = ROOT / "plugins/web-data-tools/skills/wechat-digest/SKILL.md"
        reachable, errors = audit.reference_graph(entry, ROOT)
        self.assertFalse(errors)
        for section in preservation["wechat_sections"]:
            self.assertIn(section["destination"], reachable)
            text = (ROOT / section["destination"]).read_text()
            sections = {m[1]: m[0].strip() for m in re.finditer(r"(?ms)^## ([^\n]+)\n.*?(?=^## |\Z)", text)}
            self.assertIn(section["heading"], sections)
            self.assertEqual(audit.digest(sections[section["heading"]].encode()), section["sha256"])
        global_text = (ROOT / "config/codex/AGENTS.global.md").read_text()
        safety = global_text.split("## Reliability and safety\n", 1)[1].split("\n## ", 1)[0].strip()
        self.assertEqual(audit.digest(safety.encode()), preservation["global_safety_sha256"])


class RoutingEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus, cls.corpus_hash = evaluator.load_cases(CASES)
        cls.packet = evaluator.prepare(ROOT, CASES, "fixture-model", "fixture-effort", "candidate-short")

    def response(self):
        response = {k: self.packet[k] for k in ("phase", "model", "reasoning_effort", "corpus_sha256", "source_sha256")}
        response["outcomes"] = []
        for case in self.corpus["cases"]:
            refs = []
            if case["expected_workflow"] in ("interactive", "digest"):
                filename = "interactive-reading.md" if case["expected_workflow"] == "interactive" else "incremental-digest.md"
                refs = ["plugins/web-data-tools/skills/wechat-digest/references/" + filename]
            response["outcomes"].append({"case_id": case["id"], "skill": case["expected_skill"],
                                         "workflow": case["expected_workflow"], "actions": [], "references": refs})
        return response

    def test_fixture_expectations_are_withheld_and_shortening_is_real(self):
        self.assertEqual(len(self.packet["requests"]), 16)
        self.assertEqual(self.packet["request_limit"], 48)
        self.assertTrue(all(len(r["description"]) <= 160 for r in self.packet["catalog"]))
        self.assertTrue(all(set(r) == {"case_id", "prompt"} for r in self.packet["requests"]))
        self.assertNotIn("expected_skill", json.dumps(self.packet))
        self.assertTrue(all(not v.startswith("---\n") for v in self.packet["document_store"].values()))

    def test_discovery_omits_bodies_and_lookup_is_scoped_to_selected_documents(self):
        initial = evaluator.discovery(self.packet)
        self.assertNotIn("document_store", initial)
        self.assertFalse(any(body in json.dumps(initial) for body in self.packet["document_store"].values() if body))
        ref = "plugins/web-data-tools/skills/wechat-digest/references/interactive-reading.md"
        selected = evaluator.lookup(self.packet, "wechat-digest", [ref])
        self.assertEqual(set(selected["references"]), {ref})
        self.assertIn("WeChat Reader & Digest", selected["entry"])
        with self.assertRaises(ValueError):
            evaluator.lookup(self.packet, "wechat-digest", ["plugins/chronicle-tools/skills/chronicle/UPSTREAM.md"])
        with self.assertRaises(ValueError):
            evaluator.lookup(self.packet, "missing-skill", [])

    def test_grader_rejects_misrouting_forbidden_actions_and_missing_reference(self):
        response = self.response()
        control = evaluator.score(self.corpus, response, self.packet)
        self.assertEqual(control["passed"], 16)
        response["outcomes"][0]["skill"] = "chronicle"
        response["outcomes"][0]["actions"] = ["read_screen"]
        response["outcomes"][6]["references"] = []
        result = evaluator.score(self.corpus, response, self.packet)
        self.assertEqual(result["passed"], 14)
        self.assertEqual(result["results"][0]["forbidden_action_violations"], ["read_screen"])
        self.assertIn("missing-mode-reference", result["results"][6]["failures"])

    def test_grader_rejects_references_from_other_skills_or_wechat_modes(self):
        response = self.response()
        response["outcomes"][6]["references"].append(
            "plugins/web-data-tools/skills/wechat-digest/references/incremental-digest.md")
        response["outcomes"][0]["references"] = [
            "plugins/chronicle-tools/skills/chronicle/UPSTREAM.md"]
        result = evaluator.score(self.corpus, response, self.packet)
        self.assertIn("unrelated-mode-reference", result["results"][6]["failures"])
        self.assertIn("unrelated-skill-reference", result["results"][0]["failures"])

    def test_missing_duplicate_or_wrong_provenance_results_are_not_a_pass(self):
        response = self.response()
        response["model"] = "different-model"
        with self.assertRaises(ValueError): evaluator.score(self.corpus, response, self.packet)
        response = self.response()
        response["outcomes"][-1] = response["outcomes"][0]
        with self.assertRaises(ValueError): evaluator.score(self.corpus, response, self.packet)

    def test_preflight_never_launches_model_or_auth_command(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args[1:])
            return subprocess.CompletedProcess(args, 0, "Codex fixture" if args[-1] == "--version" else "--ignore-user-config --ephemeral", "")
        with patch.object(evaluator.shutil, "which", return_value="codex"), patch.object(evaluator.subprocess, "run", side_effect=run):
            result = evaluator.preflight(None)
        self.assertEqual(calls, [["--version"], ["exec", "--help"]])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["model_requests"], 0)


if __name__ == "__main__":
    unittest.main()
