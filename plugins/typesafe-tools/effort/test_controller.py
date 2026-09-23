"""Mock-only controller tests; no Codex or Jev request is made."""

import unittest

from controller import (
    Decision,
    EffortController,
    Generation,
    ProtocolError,
    StaleDecision,
    UnknownEffort,
)
from mock_runtime import MockEvaluator, MockHost

EFFORTS = {"low", "medium", "high"}


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = EffortController("session-a", "turn-a", "medium", EFFORTS)
        self.host = MockHost("medium")

    def choose(self, effort: str = "high", generations: int = 2) -> None:
        ticket = self.controller.request_decision()
        self.controller.accept_decision(ticket, Decision(effort, generations))

    def run_generation(self, name: str) -> Generation:
        generation = self.controller.generation(name)
        self.host.start(self.controller, generation)
        self.host.finish(self.controller, generation)
        return generation

    def test_counts_generation_starts_not_tools_and_restores_baseline(self) -> None:
        self.choose()
        first = self.controller.generation("one")
        self.assertTrue(self.host.start(self.controller, first))
        self.controller.tool_result(first)
        self.controller.tool_result(first)
        self.assertFalse(self.controller.generation_started(first))
        self.assertEqual(self.controller.remaining_generations, 1)
        self.host.finish(self.controller, first)
        self.run_generation("two")
        self.assertTrue(self.controller.needs_decision)
        self.assertEqual(self.controller.remaining_generations, 0)
        self.run_generation("three")
        self.assertEqual(self.host.applied, ["high", "medium"])

    def test_all_allowed_durations_expire_at_exact_start(self) -> None:
        for duration in (1, 2, 5, 10):
            controller = EffortController(f"s-{duration}", "t", "medium", EFFORTS)
            host = MockHost("medium")
            ticket = controller.request_decision()
            controller.accept_decision(ticket, Decision("low", duration))
            for number in range(duration):
                generation = controller.generation(str(number))
                host.start(controller, generation)
                self.assertEqual(controller.remaining_generations, duration - number - 1)
                host.finish(controller, generation)
            self.assertTrue(controller.needs_decision)
            next_generation = controller.generation("next")
            host.start(controller, next_generation)
            self.assertEqual(host.applied, ["low", "medium"])

    def test_mock_evaluator_is_separate_from_mock_host(self) -> None:
        evaluator = MockEvaluator({"stuck": Decision("high", 1)})
        ticket = self.controller.request_decision()
        self.controller.accept_decision(ticket, evaluator.evaluate(ticket, "stuck"))
        self.run_generation("one")
        self.assertEqual(self.host.applied, ["high"])

    def test_manual_change_blocks_automation_until_cleared(self) -> None:
        self.choose()
        self.controller.manual_change("low")
        with self.assertRaises(ProtocolError):
            self.controller.request_decision()
        manual_generation = self.controller.generation("manual")
        self.assertIsNone(self.controller.prepare_generation(manual_generation))
        self.assertTrue(self.controller.generation_started(manual_generation))
        self.controller.generation_finished(manual_generation)
        self.controller.clear_manual_override("low")
        self.assertTrue(self.controller.needs_decision)
        next_generation = self.controller.generation("restored")
        change = self.controller.prepare_generation(next_generation)
        assert change is not None
        self.assertEqual(change.effort, "medium")

    def test_stale_ticket_and_cross_session_events_are_rejected(self) -> None:
        old = self.controller.request_decision()
        current = self.controller.request_decision()
        with self.assertRaises(StaleDecision):
            self.controller.accept_decision(old, Decision("high", 1))
        with self.assertRaises(StaleDecision):
            self.controller.prepare_generation(Generation("session-b", "turn-a", 0, "one"))
        self.controller.invalidate("new_input", turn_id="turn-b")
        with self.assertRaises(StaleDecision):
            self.controller.accept_decision(current, Decision("high", 1))
        with self.assertRaises(StaleDecision):
            self.controller.generation_started(Generation("session-a", "turn-a", 0, "one"))

    def test_manual_change_racing_with_automatic_change_needs_reconciliation(self) -> None:
        self.choose()
        change = self.controller.prepare_generation(self.controller.generation("one"))
        assert change is not None
        self.controller.manual_change("low")
        self.assertTrue(self.controller.manual_override_active)
        self.assertIsNone(self.controller.effective_effort)
        with self.assertRaises(ProtocolError):
            self.controller.acknowledge_change(change, "high")
        with self.assertRaises(UnknownEffort):
            self.controller.clear_manual_override("low")
        self.controller.reconcile("low")
        manual_generation = self.controller.generation("manual")
        self.assertIsNone(self.controller.prepare_generation(manual_generation))
        self.controller.generation_started(manual_generation)

    def test_missing_ack_blocks_start_and_late_ack_requires_reconciliation(self) -> None:
        self.choose(generations=1)
        generation = self.controller.generation("one")
        change = self.controller.prepare_generation(generation)
        assert change is not None
        self.assertEqual(change, self.controller.prepare_generation(generation))
        with self.assertRaises(UnknownEffort):
            self.controller.generation_started(generation)
        self.controller.change_outcome_unknown(change)
        self.assertIsNone(self.controller.effective_effort)
        with self.assertRaises(ProtocolError):
            self.controller.acknowledge_change(change, "high")
        with self.assertRaises(UnknownEffort):
            self.controller.request_decision()
        self.controller.reconcile("high")
        restored = self.controller.generation("restored")
        restoration = self.controller.prepare_generation(restored)
        assert restoration is not None
        self.assertEqual(restoration.effort, "medium")

    def test_mismatched_ack_does_not_claim_application(self) -> None:
        self.choose()
        change = self.controller.prepare_generation(self.controller.generation("one"))
        assert change is not None
        with self.assertRaises(UnknownEffort):
            self.controller.acknowledge_change(change, "low")
        self.assertIsNone(self.controller.effective_effort)
        self.assertFalse(self.controller.needs_decision)

    def test_invalidation_events_reject_old_decisions_and_events(self) -> None:
        for reason in ("new_input", "failure", "cancel", "resume", "compaction"):
            controller = EffortController("s", "t", "medium", EFFORTS)
            ticket = controller.request_decision()
            old_generation = controller.generation("g")
            controller.invalidate(reason, turn_id="new" if reason == "new_input" else None)
            with self.assertRaises(StaleDecision):
                controller.accept_decision(ticket, Decision("high", 1))
            with self.assertRaises(StaleDecision):
                controller.prepare_generation(old_generation)
            if reason in ("resume", "compaction"):
                self.assertIsNone(controller.effective_effort)
                controller.reconcile("medium")

    def test_invalidation_with_in_flight_change_keeps_outcome_unknown(self) -> None:
        self.choose()
        change = self.controller.prepare_generation(self.controller.generation("one"))
        assert change is not None
        self.controller.invalidate("cancel")
        self.assertIsNone(self.controller.effective_effort)
        with self.assertRaises(ProtocolError):
            self.controller.acknowledge_change(change, "high")

    def test_out_of_order_events_and_invalid_choices_fail(self) -> None:
        with self.assertRaises(ProtocolError):
            self.controller.generation_started(self.controller.generation("unprepared"))
        ticket = self.controller.request_decision()
        with self.assertRaises(ValueError):
            self.controller.accept_decision(ticket, Decision("max", 1))
        with self.assertRaises(ValueError):
            self.controller.accept_decision(ticket, Decision("high", 3))
        with self.assertRaises(ValueError):
            self.controller.accept_decision(ticket, Decision("high", True))
        self.controller.accept_decision(ticket, Decision("medium", 1))
        first = self.controller.generation("one")
        self.controller.prepare_generation(first)
        with self.assertRaises(ProtocolError):
            self.controller.prepare_generation(self.controller.generation("two"))
        self.controller.generation_started(first)
        with self.assertRaises(ProtocolError):
            self.controller.generation_finished(self.controller.generation("two"))


if __name__ == "__main__":
    unittest.main()
