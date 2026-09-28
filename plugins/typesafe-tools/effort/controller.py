"""Offline state machine for proposed reasoning-effort changes.

This module has no Codex, TypeSafe, network, or filesystem integration. A host
adapter would need to supply trustworthy generation boundaries and acknowledgments.
"""

from __future__ import annotations

from dataclasses import dataclass

DURATIONS = frozenset({1, 2, 5, 10})
INVALIDATIONS = frozenset({"new_input", "failure", "cancel", "resume", "compaction"})


class ProtocolError(ValueError):
    """An event violates the controller's ordering or identity contract."""


class StaleDecision(ProtocolError):
    """A decision or generation belongs to an earlier controller state."""


class UnknownEffort(ProtocolError):
    """The host may have applied a change whose outcome is not confirmed."""


@dataclass(frozen=True)
class Generation:
    session_id: str
    turn_id: str
    epoch: int
    generation_id: str


@dataclass(frozen=True)
class DecisionTicket:
    session_id: str
    turn_id: str
    epoch: int
    sequence: int


@dataclass(frozen=True)
class Decision:
    effort: str
    generations: int


@dataclass(frozen=True)
class EffortChange:
    sequence: int
    generation: Generation
    effort: str


@dataclass
class _ActiveDecision:
    decision: Decision
    used: int = 0


class EffortController:
    """Propose at a boundary, count confirmed starts, and fail closed on ambiguity.

    One instance owns one session. ``prepare_generation`` returns a command to
    the host only when its target differs from the last confirmed effort. The
    host must confirm that command before calling ``generation_started``.
    """

    def __init__(
        self,
        session_id: str,
        turn_id: str,
        baseline_effort: str,
        supported_efforts: set[str] | frozenset[str],
    ) -> None:
        if not session_id or not turn_id or not supported_efforts:
            raise ValueError("session, turn, and supported efforts are required")
        self.supported_efforts = frozenset(supported_efforts)
        self._validate_effort(baseline_effort)
        self.session_id = session_id
        self.turn_id = turn_id
        self.baseline_effort = baseline_effort
        self.effective_effort: str | None = baseline_effort
        self.epoch = 0
        self.manual_override_active = False
        self._ticket_sequence = 0
        self._change_sequence = 0
        self._ticket: DecisionTicket | None = None
        self._pending_decision: Decision | None = None
        self._active_decision: _ActiveDecision | None = None
        self._prepared_generation: Generation | None = None
        self._active_generation: Generation | None = None
        self._pending_change: EffortChange | None = None
        self._seen_generations: set[str] = set()

    @property
    def remaining_generations(self) -> int:
        active = self._active_decision
        return 0 if active is None else active.decision.generations - active.used

    @property
    def needs_decision(self) -> bool:
        return (
            not self.manual_override_active
            and self.effective_effort is not None
            and self._ticket is None
            and self._pending_decision is None
            and self._active_decision is None
        )

    def generation(self, generation_id: str) -> Generation:
        if not generation_id:
            raise ValueError("generation_id is required")
        return Generation(self.session_id, self.turn_id, self.epoch, generation_id)

    def request_decision(self) -> DecisionTicket:
        self._require_automatic()
        if self._prepared_generation is not None:
            raise ProtocolError("cannot change a prepared generation")
        self._ticket_sequence += 1
        self._ticket = DecisionTicket(
            self.session_id, self.turn_id, self.epoch, self._ticket_sequence
        )
        return self._ticket

    def accept_decision(self, ticket: DecisionTicket, decision: Decision) -> None:
        if ticket != self._ticket:
            raise StaleDecision("decision ticket is no longer current")
        self._require_automatic()
        self._validate_effort(decision.effort)
        if type(decision.generations) is not int or decision.generations not in DURATIONS:
            raise ValueError("duration must be 1, 2, 5, or 10 generations")
        self._ticket = None
        self._pending_decision = decision

    def prepare_generation(self, generation: Generation) -> EffortChange | None:
        self._check_generation(generation)
        if self._active_generation is not None:
            raise ProtocolError("a generation is already active")
        if generation.generation_id in self._seen_generations:
            raise ProtocolError("generation has already started")
        if self._prepared_generation not in (None, generation):
            raise ProtocolError("a different generation is already prepared")
        self._prepared_generation = generation
        if self.manual_override_active:
            return None
        if self.effective_effort is None:
            raise UnknownEffort("reconcile effective effort before another generation")
        if self._pending_change is not None:
            return self._pending_change
        target = self._target_effort()
        if target == self.effective_effort:
            return None
        self._change_sequence += 1
        self._pending_change = EffortChange(self._change_sequence, generation, target)
        return self._pending_change

    def acknowledge_change(self, change: EffortChange, observed_effort: str) -> None:
        if change != self._pending_change:
            raise ProtocolError("change is stale or was not requested")
        if observed_effort != change.effort:
            self.invalidate("cancel")
            raise UnknownEffort("host did not confirm the requested effort")
        self._pending_change = None
        self.effective_effort = observed_effort

    def change_outcome_unknown(self, change: EffortChange) -> None:
        if change != self._pending_change:
            raise ProtocolError("change is stale or was not requested")
        self.invalidate("cancel")

    def generation_started(self, generation: Generation) -> bool:
        self._check_generation(generation)
        if generation.generation_id in self._seen_generations:
            return False
        if generation != self._prepared_generation or self._active_generation is not None:
            raise ProtocolError("generation started outside its prepared boundary")
        if self._pending_change is not None or self.effective_effort is None:
            raise UnknownEffort("effort change has not been confirmed")
        if not self.manual_override_active and self.effective_effort != self._target_effort():
            raise ProtocolError("effective effort differs from the selected effort")
        if not self.manual_override_active:
            if self._pending_decision is not None:
                self._active_decision = _ActiveDecision(self._pending_decision)
                self._pending_decision = None
            if self._active_decision is not None:
                self._active_decision.used += 1
                if self.remaining_generations == 0:
                    self._active_decision = None
        self._active_generation = generation
        self._prepared_generation = None
        self._seen_generations.add(generation.generation_id)
        return True

    def tool_result(self, generation: Generation) -> None:
        """Record an ordinary tool result without consuming a generation."""
        self._check_generation(generation)
        if generation != self._active_generation:
            raise ProtocolError("tool result does not belong to the active generation")

    def generation_finished(self, generation: Generation) -> None:
        self._check_generation(generation)
        if generation != self._active_generation:
            raise ProtocolError("generation finish is out of order")
        self._active_generation = None

    def invalidate(self, reason: str, *, turn_id: str | None = None) -> None:
        if reason not in INVALIDATIONS:
            raise ValueError("unknown invalidation reason")
        if reason == "new_input" and not turn_id:
            raise ValueError("new_input requires the new turn ID")
        if turn_id is not None and not turn_id:
            raise ValueError("turn ID cannot be empty")
        if self._pending_change is not None or reason in {"resume", "compaction"}:
            self.effective_effort = None
        self.epoch += 1
        if turn_id is not None:
            self.turn_id = turn_id
        self._ticket = None
        self._pending_decision = None
        self._active_decision = None
        self._prepared_generation = None
        self._active_generation = None
        self._pending_change = None
        self._seen_generations.clear()

    def manual_change(self, observed_effort: str) -> None:
        """A host-observed manual change suspends automatic control."""
        self._validate_effort(observed_effort)
        automatic_change_in_flight = self._pending_change is not None
        self.invalidate("cancel")
        self.effective_effort = None if automatic_change_in_flight else observed_effort
        self.manual_override_active = True

    def clear_manual_override(self, observed_effort: str) -> None:
        if not self.manual_override_active:
            raise ProtocolError("manual control is not active")
        if self.effective_effort is None:
            raise UnknownEffort("reconcile the in-flight change before clearing manual control")
        self._validate_effort(observed_effort)
        self.invalidate("cancel")
        self.effective_effort = observed_effort
        self.manual_override_active = False

    def reconcile(self, observed_effort: str) -> None:
        """Resume after an unknown host outcome using an independent observation."""
        if self.effective_effort is not None:
            raise ProtocolError("reconciliation requires an unknown effective effort")
        if self._active_generation is not None or self._pending_change is not None:
            raise ProtocolError("cannot reconcile during an active generation or change")
        self._validate_effort(observed_effort)
        self.effective_effort = observed_effort

    def _target_effort(self) -> str:
        if self._pending_decision is not None:
            return self._pending_decision.effort
        if self._active_decision is not None:
            return self._active_decision.decision.effort
        return self.baseline_effort

    def _require_automatic(self) -> None:
        if self.manual_override_active:
            raise ProtocolError("manual override suspends automatic decisions")
        if self.effective_effort is None:
            raise UnknownEffort("effective effort is unknown")

    def _validate_effort(self, effort: str) -> None:
        if effort not in self.supported_efforts:
            raise ValueError("effort is not supported by this model catalog")

    def _check_generation(self, generation: Generation) -> None:
        if (
            generation.session_id != self.session_id
            or generation.turn_id != self.turn_id
            or generation.epoch != self.epoch
        ):
            raise StaleDecision("generation belongs to another session, turn, or epoch")
