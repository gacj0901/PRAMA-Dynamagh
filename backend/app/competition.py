"""Competition-mode budget profile without changing the existing spend path."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any

from app.public_safety import M2M_MAX_WORKFLOW_USDC, public_daily_spend_cap_usdc, public_max_mandate_usdc


def _configured_decimal(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return default
    return value if value >= 0 else default


def competition_budget_profile() -> dict[str, Any]:
    """Return effective limits; this function never authorizes spend.

    The public acquisition route remains one task per mandate.  A future
    multi-call profile must first add a coordinated worker contract, so this
    surface reports the current effective call count rather than implying one.
    """

    configured_workflow = _configured_decimal(
        "COMPETITION_MAX_WORKFLOW_USDC",
        public_max_mandate_usdc(),
    )
    effective_workflow = min(configured_workflow, public_max_mandate_usdc(), M2M_MAX_WORKFLOW_USDC)
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
        "max_real_calls_per_workflow": 1,
        "multi_intent_enabled": False,
        "g12_hard_cap_applied": effective_workflow < configured_workflow,
        "operator_approval_required_for_raise": True,
    }
