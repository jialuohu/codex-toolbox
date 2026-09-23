"""Deterministic, network-free evaluator and host for the effort prototype."""

from controller import Decision, DecisionTicket, EffortController, Generation


class MockEvaluator:
    def __init__(self, decisions: dict[str, Decision]) -> None:
        self.decisions = decisions

    def evaluate(self, ticket: DecisionTicket, signal: str) -> Decision:
        if not ticket.session_id or not ticket.turn_id:
            raise ValueError("ticket must identify a session and turn")
        return self.decisions[signal]


class MockHost:
    def __init__(self, effective_effort: str) -> None:
        self.effective_effort = effective_effort
        self.applied: list[str] = []

    def start(self, controller: EffortController, generation: Generation) -> bool:
        change = controller.prepare_generation(generation)
        if change is not None:
            self.effective_effort = change.effort
            self.applied.append(change.effort)
            controller.acknowledge_change(change, self.effective_effort)
        return controller.generation_started(generation)

    def finish(self, controller: EffortController, generation: Generation) -> None:
        controller.generation_finished(generation)
