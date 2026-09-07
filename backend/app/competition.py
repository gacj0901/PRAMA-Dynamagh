"""Competition-mode budget profile without changing the existing spend path."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any

from app.public_safety import (
    MAX_SINGLE_ACQUISITION_USDC,
    M2M_MAX_WORKFLOW_USDC,
    public_daily_spend_cap_usdc,
    public_max_mandate_usdc,
)


DEFAULT_MAX_CALLS_PER_WORKFLOW = 5
MIN_MAX_CALLS_PER_WORKFLOW = 1
MAX_MAX_CALLS_PER_WORKFLOW = 5


def _configured_decimal(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return default
    return value if value >= 0 else default


def competition_max_calls_per_workflow() -> int:
    """Return the structural acquisition fan-out ceiling.

    This controls only how many caller-supplied acquisition tasks may be
    sequenced.  G12 budget reservation and settlement remain authoritative for
    whether each task may contact Telegraph.
    """

    raw = os.environ.get("FANOUT_MAX_TASKS_PER_MANDATE", os.environ.get("COMPETITION_MAX_CALLS_PER_WORKFLOW"))
    if raw is None:
        return DEFAULT_MAX_CALLS_PER_WORKFLOW
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return MIN_MAX_CALLS_PER_WORKFLOW
    return min(max(value, MIN_MAX_CALLS_PER_WORKFLOW), MAX_MAX_CALLS_PER_WORKFLOW)


def competition_budget_profile() -> dict[str, Any]:
    """Return effective limits; this function never authorizes spend.

    The public acquisition route accepts a bounded ordered list of caller
    supplied tasks.  Telegraph still selects the actual Miner and returned
    Intent for each query; this profile does not classify query semantics.
    """

    configured_workflow = _configured_decimal(
        "COMPETITION_MAX_WORKFLOW_USDC",
        public_max_mandate_usdc(),
    )
    effective_workflow = min(configured_workflow, public_max_mandate_usdc())
    configured_daily = _configured_decimal(
        "COMPETITION_DAILY_SPEND_CAP_USDC",
        public_daily_spend_cap_usdc(),
    )
    effective_daily = min(configured_daily, public_daily_spend_cap_usdc())
    return {
        "configured_max_usdc_per_workflow": f"{configured_workflow:.6f}",
        "effective_max_usdc_per_workflow": f"{effective_workflow:.6f}",
        "configured_daily_spend_cap_usdc": f"{configured_daily:.6f}",
        "effective_daily_spend_cap_usdc": f"{effective_daily:.6f}",
        "max_single_acquisition_usdc": f"{MAX_SINGLE_ACQUISITION_USDC:.6f}",
        "max_real_calls_per_workflow": competition_max_calls_per_workflow(),
        "fanout_max_tasks_per_mandate": competition_max_calls_per_workflow(),
        "m2m_max_workflow_usdc": f"{M2M_MAX_WORKFLOW_USDC:.6f}",
        "multi_intent_enabled": competition_max_calls_per_workflow() > 1,
        "g12_hard_cap_applied": effective_workflow < configured_workflow,
        "operator_approval_required_for_raise": True,
    }
