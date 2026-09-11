"""Static caller/callee contract for authority-boundary functions.

Root-cause regression guard for the incident where acquisition.py passed
``recovery_probe_authorized`` to ``run_pre_next_action_authority_check`` while
the function did not declare it: every AUTONOMOUS acquisition died with a
TypeError at PRE_NETWORK and was misclassified as GATEWAY_UNAVAILABLE.

This test parses call sites with ``ast`` and asserts every keyword argument
passed exists in the callee signature -- no runtime, no DB, no network.
"""
import ast
import inspect
import importlib

import pytest

AUTHORITY_CONTRACTS = [
    ("app.workers.acquisition", "app.authority.runtime", "run_pre_next_action_authority_check"),
    ("app.workers.acquisition", "app.authority.runtime", "evaluate_current_g13"),
    ("app.workers.acquisition", "app.authority.delegated", "issue_execution_permit"),
    ("app.workers.acquisition", "app.authority.delegated", "consume_execution_permit"),
    ("app.authority.runtime", "app.authority.composition", "evaluate_authority_composition"),
]


def _called_args(module_path: str, func_name: str) -> list[tuple[int, set[str]]]:
    """(positional_count, keyword_names) for every call site of ``func_name``."""
    tree = ast.parse(inspect.getsource(importlib.import_module(module_path)))
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name:
            calls.append((len(node.args), {kw.arg for kw in node.keywords if kw.arg is not None}))
    return calls


@pytest.mark.parametrize("caller_module, callee_module, func_name", AUTHORITY_CONTRACTS)
def test_authority_call_site_matches_signature(caller_module, callee_module, func_name):
    callee = getattr(importlib.import_module(callee_module), func_name)
    sig = inspect.signature(callee)
    accepted = set(sig.parameters)
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    has_var_pos = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
    # Positional capacity: parameters that can be filled positionally.
    positional_ok = {
        name for name, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    }
    required_positional = {
        name for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    }
    calls = _called_args(caller_module, func_name)
    assert calls, f"no call site found for {func_name} in {caller_module} — test is vacuous"
    for n_positional, keywords in calls:
        if not has_var_pos:
            assert n_positional <= len(positional_ok), (
                f"{caller_module} passes {n_positional} positional args to "
                f"{callee_module}:{func_name}, which accepts at most {len(positional_ok)} "
                f"({sorted(positional_ok)})"
            )
        if not has_var_kw:
            unknown = keywords - accepted
            assert not unknown, (
                f"{caller_module} passes {sorted(unknown)} to {callee_module}:{func_name}, "
                f"which accepts {sorted(accepted)} — caller/callee signature drift"
            )
        # Required parameters must be covered positionally or by keyword.
        covered_by_position = set(sorted(positional_ok)[:n_positional])
        missing = required_positional - covered_by_position - keywords
        assert not missing, (
            f"{caller_module} call to {callee_module}:{func_name} omits required "
            f"parameters {sorted(missing)}"
        )
