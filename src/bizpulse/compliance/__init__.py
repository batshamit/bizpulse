"""Compliance & policy alignment layer.

`policies` is a static registry of regulations that apply to BizPulse's three
industries across India + EU + US + UK. The compliance_checker agent uses
this registry to score MarketingStrategy outputs against applicable rules.
"""

from __future__ import annotations

from bizpulse.compliance.policies import (
    POLICIES,
    applicable,
    list_policies,
    supported_countries,
    supported_states,
)

__all__ = [
    "POLICIES",
    "applicable",
    "list_policies",
    "supported_countries",
    "supported_states",
]
