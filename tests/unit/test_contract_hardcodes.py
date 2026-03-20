"""Regression test ensuring the pipeline stays contract-driven.

The active dataset supplies column names such as `trade_value_usd` or
`port_code`. These literals should live exclusively inside the dataset
contract, not in the application code. Keeping this guard prevents new
hardcoded references from creeping into the pipeline when additional
metrics or datasets are onboarded.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Tokens that must never appear inside data_analyst_agent/*.py. Each entry maps to
# a contract-scoped column or hierarchy member that would break dataset portability
# if it leaked into the pipeline implementation.
BANNED_LITERALS = {
    "trade_value_usd",
    "volume_units",
    "port_code",
    "port_name",
    "hs2",
    "hs2_name",
    "hs4",
    "hs4_name",
    "state_name",
}


def _python_sources() -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    agent_dir = project_root / "data_analyst_agent"
    return [p for p in agent_dir.rglob("*.py") if p.is_file()]


@pytest.mark.parametrize("literal", sorted(BANNED_LITERALS))
def test_pipeline_has_no_trade_specific_literals(literal: str) -> None:
    offenders: list[Path] = []
    for py_file in _python_sources():
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if literal in text:
            offenders.append(py_file)
    assert not offenders, (
        f"Found forbidden literal '{literal}' in files:\n"
        + "\n".join(str(path.relative_to(Path(__file__).resolve().parents[2])) for path in offenders)
    )
