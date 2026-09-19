"""Audited billing facts, never a caller-controlled verification switch.

The public context limit and price do not establish a maximum billable cost.
No real evidence is approved in v0.1.0. Adding an entry requires a separately
reviewed provider guarantee, validity interval, model, and maximum charge.
Unit tests inject fictional bounds; they are not production configuration.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

MODEL = "jev-1.13.0"
NANOUSD = 1_000_000_000
MONTHLY_CAP = 5 * NANOUSD


@dataclass(frozen=True)
class BillingBound:
    evidence_id: str
    model: str
    max_input_tokens: int
    nanousd_per_input_token: int
    valid_until: datetime
    source: str
    # The inspected model prices outputs at zero. A future audited bound must
    # guarantee that as well as the input price/quantity and absence of other fees.
    # Models with billed outputs require a separately implemented accounting contract.
    nanousd_per_output_token: int = 0

    @property
    def reservation(self) -> int:
        return self.max_input_tokens * self.nanousd_per_input_token

    def valid(self, now: datetime) -> bool:
        return (self.model == MODEL and 0 < self.reservation <= MONTHLY_CAP
                and self.max_input_tokens > 0 and self.nanousd_per_input_token > 0
                and self.valid_until.tzinfo is not None and now < self.valid_until
                and self.source.startswith("https://") and self.nanousd_per_output_token == 0)


VERIFIED_BOUNDS: Mapping[str, BillingBound] = MappingProxyType({})
# A passed pilot must be reviewed separately; configuration alone is not evidence.
VERIFIED_PILOTS: frozenset[str] = frozenset()
