"""Materiality gate wrapper for narrative generation."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from ..utils.env_utils import parse_bool_env
from ..sub_agents.narrative_agent.agent import create_narrative_agent


def _get_nested(obj: Any, *keys: str, default: Any = None) -> Any:
    current = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return default
    return current


def _as_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _parse_cards(level_payload: Any) -> list[dict[str, Any]]:
    payload = _as_dict(level_payload)
    cards = payload.get("insight_cards")
    if isinstance(cards, list):
        return [card for card in cards if isinstance(card, dict)]
    return []


def _delta_from_card(card: dict[str, Any]) -> tuple[float, float]:
    evidence = card.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    pct_candidates = (
        evidence.get("delta_pct"),
        evidence.get("variance_pct"),
        card.get("delta_pct"),
        card.get("variance_pct"),
    )
    abs_candidates = (
        evidence.get("delta_abs"),
        evidence.get("variance_abs"),
        evidence.get("variance_dollar"),
        card.get("delta_abs"),
        card.get("variance_abs"),
        card.get("variance_dollar"),
    )

    def _first_number(candidates: tuple[Any, ...]) -> float:
        for val in candidates:
            try:
                if val is None:
                    continue
                return float(val)
            except (TypeError, ValueError):
                continue
        return 0.0

    return abs(_first_number(pct_candidates)), abs(_first_number(abs_candidates))


def _has_high_severity_anomaly(state: dict[str, Any]) -> bool:
    stats_payload = _as_dict(state.get("statistical_summary"))
    anomalies = stats_payload.get("anomalies")
    if not isinstance(anomalies, list):
        return False
    for anomaly in anomalies:
        if not isinstance(anomaly, dict):
            continue
        severity = str(anomaly.get("severity", "")).strip().lower()
        if severity in {"high", "critical"}:
            return True
    return False


def _materiality_thresholds(state: dict[str, Any]) -> tuple[float, float]:
    contract = state.get("dataset_contract")
    threshold_pct = _get_nested(contract, "materiality", "variance_pct", default=5.0)
    threshold_abs = _get_nested(contract, "materiality", "variance_absolute", default=10000.0)
    try:
        threshold_pct_f = abs(float(threshold_pct))
    except (TypeError, ValueError):
        threshold_pct_f = 5.0
    try:
        threshold_abs_f = abs(float(threshold_abs))
    except (TypeError, ValueError):
        threshold_abs_f = 10000.0
    return threshold_pct_f, threshold_abs_f


def has_material_findings(state: dict[str, Any]) -> bool:
    """Return True when hierarchical/stats findings exceed materiality thresholds."""
    threshold_pct, threshold_abs = _materiality_thresholds(state)

    for level in range(8):
        cards = _parse_cards(state.get(f"level_{level}_analysis"))
        for card in cards:
            delta_pct, delta_abs = _delta_from_card(card)
            if delta_pct >= threshold_pct or delta_abs >= threshold_abs:
                return True

    return _has_high_severity_anomaly(state)


def build_template_summary(state: dict[str, Any]) -> str:
    target = state.get("current_analysis_target") or state.get("analysis_target") or "metric"
    period = state.get("analysis_period") or "the current analysis period"
    return (
        f"No material variance was detected for {target} in {period}; "
        "results remained within configured materiality thresholds."
    )


def _skip_narrative_enabled() -> bool:
    return parse_bool_env(os.getenv("SKIP_NARRATIVE_BELOW_MATERIALITY", "true"))


class ConditionalNarrativeAgent(BaseAgent):
    """Runs narrative LLM only when material findings exist."""

    def __init__(self, wrapped_agent: BaseAgent):
        super().__init__(name="conditional_narrative_agent")
        object.__setattr__(self, "wrapped_agent", wrapped_agent)
        object.__setattr__(self, "output_key", "narrative_results")
        object.__setattr__(self, "description", "Materiality-gated narrative wrapper")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if not _skip_narrative_enabled() or has_material_findings(state):
            async for event in self.wrapped_agent.run_async(ctx):
                yield event
            return

        payload = {
            "insight_cards": [],
            "narrative_summary": build_template_summary(state),
            "recommended_actions": [],
            "meta": {
                "narrative_skipped": True,
                "reason": "below_materiality",
            },
        }
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"narrative_results": json.dumps(payload)}),
        )


def create_conditional_narrative_agent() -> BaseAgent:
    return ConditionalNarrativeAgent(create_narrative_agent())
