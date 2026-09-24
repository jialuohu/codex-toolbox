"""Execute the copyable TypeSafe computer-use recipes against fixture-shaped AX text."""

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "plugins/typesafe-tools/skills/typesafe-computer-use/SKILL.md").read_text()
HELPERS = (ROOT / "plugins/typesafe-tools/skills/typesafe-computer-use/scripts/helpers.js").read_text()
ACTION = re.search(r"```javascript\n(var cuBefore = await target\.getAXState.*?\n)```", SKILL, re.DOTALL).group(1)
OBSERVE = re.search(r"```javascript\n(var cuAx = await target\.getAXState.*?\n)```", SKILL, re.DOTALL).group(1)

NATIVE_RESULT = re.search(r"// cu-native-result-begin\n(.*?)\n// cu-native-result-end", SKILL, re.DOTALL).group(1)

# This is the index/role/label layout captured from the disposable browser fixture.
AX = """0 AXWebArea Computer Use Browser Fixture
\t1 container
\t\t2 text Goal: Use the Open button in the Quartz row.
\t7 container Description: Fixture workspace, ID: workspace
\t\t10 text Quartz
\t\t11 text Research · Ready
\t\t12 button Open
\t\t13 text Cedar
\t\t14 text Operations · Active
\t\t15 button Open
\t\t16 text Nimbus
\t\t17 text Design · Review
\t\t18 button Open
\t22 container Task result
\t\t23 text Task incomplete
\t\t24 text Wrong actions: 0"""
NATIVE_AX = """0 window Computer Use Native Fixture
\t7 scroll area Records (showing 0-2 of 2 items)
\t\t98 text Quartz Research · Ready
\t\t99 button Open
\t\t100 text Cedar Operations · Active
\t\t101 button Open
\t102 text Wrong actions: 0"""
NATIVE_RESULT_LINE = "\t\t102 text Value: PASS native-long_tree-0 Wrong actions: 0, ID: fixture-result"
NATIVE_PARTIAL_RESULT = """0 window Computer Use Native Fixture
\t1 container
\t\t7 scroll area Records (showing 0-100 of 120 items)
\t\t\t98 text Quartz Research · Ready
\t\t\t99 button Open
""" + NATIVE_RESULT_LINE


def js(expression, data=None):
    script = HELPERS + "\nconst input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + expression
    result = subprocess.run(["node", "-e", script], input=json.dumps(data or {}), text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def binding(state=AX, **changes):
    spec = {"stateKind": "full", "role": "button", "label": "Open", "context": ["Quartz"],
            "operation": "click", "preconditions": ["present", "enabled"]}
    spec.update(changes)
    return js("console.log(JSON.stringify(cuMatchUnique(input.state, input.spec)));",
              {"state": state, "spec": spec})


def action(pre=AX, post=AX, throws=False, post_full=None, full_throws=False):
    script = """
const calls = [];
const writes = [];
let reads = 0;
var nodeRepl = { write(value) { writes.push(JSON.parse(value)); } };
var target = {
  async getAXState(options) {
    calls.push(options?.disableDiffing ? 'full' : 'state');
    reads++;
    if (reads === 1) return input.pre;
    if (reads > 2 && input.full_throws) throw new Error('full observation unavailable');
    return reads > 2 && input.post_full !== null ? input.post_full : input.post;
  },
  async click(index) { calls.push(['click', index]); if (input.throws) throw new Error('action error after effect'); }
};
(async () => {
""" + ACTION + """
  console.log(JSON.stringify({ calls, writes }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    return js(script, {"pre": pre, "post": post, "throws": throws,
                       "post_full": post_full, "full_throws": full_throws})


def observe(first, full):
    script = """
const calls = [], writes = [];
var nodeRepl = { write(value) { writes.push(value); } };
var target = { async getAXState(options) {
  calls.push(options?.disableDiffing ? 'full' : 'state');
  return calls.length === 1 ? input.first : input.full;
} };
(async () => {
""" + OBSERVE + """
  console.log(JSON.stringify({ calls, writes }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    return js(script, {"first": first, "full": full})


def native_result(state):
    script = """
const calls = [], writes = [];
var nodeRepl = { write(value) { writes.push(JSON.parse(value)); } };
var target = { async getAXState(options) {
  calls.push(options?.disableDiffing ? 'full' : 'state');
  return input.state;
} };
(async () => {
""" + NATIVE_RESULT + """
  console.log(JSON.stringify({ calls, writes }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    return js(script, {"state": state})


class ExcerptSelection(unittest.TestCase):
    def test_small_tree_and_useful_diff_are_direct(self):
        for full in (True, False):
            view = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { terms: ['Quartz'], full: input.full })));",
                      {"state": AX, "full": full})
            self.assertTrue(view["direct"])
            self.assertEqual(view["text"], AX)
            self.assertEqual(view["omitted_lines"], 0)

    def test_long_tree_keeps_controls_ancestors_and_omission_count(self):
        state = "0 AXWebArea Fixture\n\t1 container Description: Workspace\n" + "\n".join(
            f"\t\t{i} text unrelated {i}" for i in range(2, 152)) + "\n\t\t152 text Quartz\n\t\t153 text Research · Ready\n\t\t154 button Open"
        view = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { terms: ['Quartz', 'button Open'], full: true })));",
                  {"state": state})
        self.assertFalse(view["direct"])
        self.assertIn("152 text Quartz", view["text"])
        self.assertIn("154 button Open", view["text"])
        self.assertIn("1 container Description: Workspace", view["text"])
        self.assertEqual(view["total_lines"], view["shown_lines"] + view["omitted_lines"])
        self.assertLessEqual(view["shown_lines"], 80)

    def test_soft_budget_never_discards_matching_context(self):
        state = "\n".join(f"{i} text Quartz row {i}" for i in range(120))
        view = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { terms: ['Quartz'], full: true })));",
                  {"state": state})
        self.assertTrue(view["direct"])
        self.assertEqual(view["shown_lines"], 120)

    def test_incomplete_diff_requests_full_state_in_same_call(self):
        for fragment in ("12 button Open", "24 text Wrong actions: 0", "... 20 lines omitted"):
            view = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { terms: ['Quartz'], required: ['Quartz', 'Wrong actions'] })));",
                      {"state": fragment})
            self.assertTrue(view["needsFull"])
        full = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { terms: ['Quartz'], full: true })));",
                  {"state": AX})
        self.assertFalse(full["needsFull"])
        self.assertIn("disableDiffing: true", ACTION)

    def test_native_viewport_range_falls_back_even_when_tree_is_small(self):
        for marker in ("showing 0-100 of 120 items", "showing 20-120 of 120 items"):
            partial = NATIVE_AX.replace("showing 0-2 of 2 items", marker)
            with self.subTest(marker=marker):
                view = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { full: false })));",
                          {"state": partial})
                self.assertTrue(view["needsFull"])
                self.assertEqual(view["reason"], "partial tree")
                result = observe(partial, partial)
                self.assertEqual(result["calls"], ["state", "full"])
                emitted = json.loads(result["writes"][0])
                self.assertTrue(emitted["incomplete"])
                self.assertIn(marker, emitted["text"])
                full = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { full: true })));",
                          {"state": partial})
                self.assertTrue(full["incomplete"])
        complete = js("console.log(JSON.stringify(cuSelectExcerpt(input.state, { full: true })));",
                      {"state": NATIVE_AX})
        self.assertFalse(complete["incomplete"])

    def test_native_full_fallback_can_restore_complete_coverage(self):
        partial = NATIVE_AX.replace("showing 0-2 of 2 items", "showing 0-100 of 120 items")
        result = observe(partial, NATIVE_AX)
        self.assertEqual(result["calls"], ["state", "full"])
        self.assertIn("showing 0-2 of 2 items", result["writes"][0])
        self.assertFalse(result["writes"][0].startswith("{"))
        complete = observe(AX, AX)
        self.assertEqual(complete["calls"], ["state"])
        self.assertEqual(complete["writes"], [AX])


class UniqueBinding(unittest.TestCase):
    def test_duplicate_open_labels_bind_only_to_exact_row(self):
        self.assertEqual(binding(), {"status": "bound", "index": 12})
        self.assertEqual(binding(context=["Cedar"]), {"status": "bound", "index": 15})
        self.assertEqual(binding(context=["Quartz", "Research · Ready"]), {"status": "bound", "index": 12})

    def test_goal_text_is_not_row_context_and_label_is_exact(self):
        state = AX.replace("\t\t10 text Quartz\n\t\t11 text Research · Ready\n\t\t12 button Open\n", "")
        self.assertEqual(binding(state)["status"], "unbound")
        self.assertEqual(binding(label="Open Quartz")["status"], "unbound")
        self.assertEqual(binding(role="tab")["status"], "unbound")
        self.assertEqual(binding(AX.replace("12 button Open", "12 button Open, Value Pack"))["status"], "unbound")

    def test_unrelated_sibling_control_breaks_row_context(self):
        state = "0 AXWebArea Fixture\n\t1 container\n\t\t2 text Quartz\n\t\t3 textfield Search\n\t\t4 button Open"
        self.assertEqual(binding(state)["status"], "unbound")

    def test_reordered_indices_require_new_full_state(self):
        reordered = AX.replace("\t\t10 text Quartz\n\t\t11 text Research · Ready\n\t\t12 button Open\n", "")
        reordered = reordered.replace("\t\t16 text Nimbus", "\t\t31 text Quartz\n\t\t32 text Research · Ready\n\t\t33 button Open\n\t\t16 text Nimbus")
        self.assertEqual(binding(reordered), {"status": "bound", "index": 33})
        self.assertEqual(action(pre=reordered)["calls"][1], ["click", 33])

    def test_missing_disabled_and_ambiguous_target_are_unbound(self):
        missing = AX.replace("\t\t12 button Open", "\t\t12 text Open")
        disabled = AX.replace("\t\t12 button Open", "\t\t12 button Open, Enabled: false")
        duplicate = AX.replace("\t\t13 text Cedar", "\t\t25 text Quartz\n\t\t26 text Research · Ready\n\t\t27 button Open\n\t\t13 text Cedar")
        for state in (missing, disabled, duplicate):
            with self.subTest(state=state):
                self.assertEqual(binding(state)["status"], "unbound")

    def test_incomplete_diff_and_unsupported_structure_are_unbound(self):
        self.assertEqual(binding(stateKind="diff")["status"], "unbound")
        self.assertEqual(binding(AX + "\n... 2 lines omitted")["status"], "unbound")
        self.assertEqual(binding("button Open [12]", context=["Quartz"])["status"], "unbound")
        self.assertEqual(binding(operation="drag")["status"], "unbound")
        self.assertEqual(binding(preconditions=["authenticated"])["status"], "unbound")
        self.assertEqual(binding(context=[""])["status"], "unbound")
        self.assertEqual(binding(context=["  "])["status"], "unbound")
        self.assertEqual(binding(label="")["status"], "unbound")

    def test_selection_precondition_must_be_observed(self):
        state = "0 AXWebArea Fixture\n\t1 container\n\t\t2 text Quartz\n\t\t3 tab Pending, Selected: false"
        spec = {"stateKind": "full", "role": "tab", "label": "Pending", "context": ["Quartz"],
                "operation": "click", "preconditions": ["not_selected"]}
        self.assertEqual(binding(state, **spec), {"status": "bound", "index": 3})
        self.assertEqual(binding(state.replace("Selected: false", "Value: false"), **spec)["status"], "unbound")

    def test_native_combined_row_text_requires_exact_context(self):
        self.assertEqual(binding(NATIVE_AX, context=["Quartz Research · Ready"]),
                         {"status": "bound", "index": 99})
        self.assertEqual(binding(NATIVE_AX, context=["Quartz"])["status"], "unbound")
        for marker in ("showing 0-100 of 120 items", "showing 20-120 of 120 items"):
            partial = NATIVE_AX.replace("showing 0-2 of 2 items", marker)
            with self.subTest(marker=marker):
                self.assertEqual(binding(partial, context=["Quartz Research · Ready"]),
                                 {"status": "unbound", "reason": "incomplete state"})


class ActionRecipe(unittest.TestCase):
    def test_single_action_bypasses_helper_initialization(self):
        block = re.search(r"For a single obvious action.*?```javascript\n(.*?)\n```", SKILL, re.DOTALL).group(1)
        self.assertIn("await target.click(freshIndex);", block)
        self.assertIn("await target.getAXState();", block)
        self.assertNotIn("cuSelectExcerpt", block)

    def test_action_error_with_successful_side_effect_is_observed_once(self):
        post = AX.replace("23 text Task incomplete", "23 text PASS browser-duplicate_label-0")
        result = action(post=post, throws=True)
        self.assertEqual(result["calls"], ["full", ["click", 12], "state"])
        self.assertTrue(result["writes"][0]["verified"])
        self.assertIn("action error after effect", result["writes"][0]["action_error"])

    def test_failed_verification_remains_unverified(self):
        result = action()
        self.assertEqual(result["calls"], ["full", ["click", 12], "state", "full"])
        self.assertFalse(result["writes"][0]["verified"])
        self.assertTrue(result["writes"][0]["result"]["incomplete"])
        self.assertNotIn("PASS browser-duplicate_label-0", result["writes"][0]["result"]["text"])

    def test_post_action_incomplete_diff_gets_full_state_in_same_call(self):
        post = AX.replace("23 text Task incomplete", "23 text PASS browser-duplicate_label-0")
        result = action(post="23 text PASS browser-duplicate_label-0", post_full=post)
        self.assertEqual(result["calls"], ["full", ["click", 12], "state", "full"])
        self.assertTrue(result["writes"][0]["verified"])
        missing_marker = action(post="24 text Wrong actions: 0", post_full=post)
        self.assertEqual(missing_marker["calls"], ["full", ["click", 12], "state", "full"])
        self.assertTrue(missing_marker["writes"][0]["verified"])
        failed_fallback = action(post="23 text PASS browser-duplicate_label-0", full_throws=True)
        self.assertFalse(failed_fallback["writes"][0]["verified"])
        self.assertIn("full observation unavailable", failed_fallback["writes"][0]["observation_error"])

    def test_post_action_partial_full_state_exposes_incomplete_flag(self):
        post = AX.replace("23 text Task incomplete", "23 text PASS browser-duplicate_label-0")
        post += "\n\t25 scroll area Records (showing 0-100 of 120 items)"
        result = action(post=post, post_full=post)
        self.assertEqual(result["calls"], ["full", ["click", 12], "state", "full"])
        self.assertFalse(result["writes"][0]["verified"])
        self.assertTrue(result["writes"][0]["result"]["incomplete"])
        self.assertIn("showing 0-100 of 120 items", result["writes"][0]["result"]["text"])

    def test_helper_reset_reinitializes_without_ui_binding_cache(self):
        first = binding()
        second = binding(AX.replace("\t\t12 button Open", "\t\t42 button Open"))
        self.assertEqual(first["index"], 12)
        self.assertEqual(second["index"], 42)


class NativeResultRecipe(unittest.TestCase):
    def test_combined_result_verifies_despite_unrelated_partial_list(self):
        result = native_result(NATIVE_PARTIAL_RESULT)
        self.assertEqual(result["calls"], ["full"])
        self.assertEqual(result["writes"], [{"verified": True, "result": NATIVE_RESULT_LINE}])

    def test_wrong_case_nonzero_or_missing_counter_is_unverified(self):
        for line in (
            NATIVE_RESULT_LINE.replace("native-long_tree-0", "native-long_tree-1"),
            NATIVE_RESULT_LINE.replace("Wrong actions: 0", "Wrong actions: 1"),
            NATIVE_RESULT_LINE.replace(" Wrong actions: 0", ""),
        ):
            with self.subTest(line=line):
                result = native_result(NATIVE_PARTIAL_RESULT.replace(NATIVE_RESULT_LINE, line))
                self.assertFalse(result["writes"][0]["verified"])

    def test_truncated_missing_or_duplicate_result_is_unverified(self):
        for state in (
            NATIVE_PARTIAL_RESULT.replace(" Wrong actions: 0,", " ... Wrong actions: 0,"),
            NATIVE_PARTIAL_RESULT.replace(NATIVE_RESULT_LINE, ""),
            NATIVE_PARTIAL_RESULT + "\n" + NATIVE_RESULT_LINE.replace("102 text", "103 text"),
            NATIVE_PARTIAL_RESULT.replace(NATIVE_RESULT_LINE, "\t" + NATIVE_RESULT_LINE),
        ):
            with self.subTest(state=state):
                result = native_result(state)
                self.assertFalse(result["writes"][0]["verified"])


if __name__ == "__main__":
    unittest.main()
