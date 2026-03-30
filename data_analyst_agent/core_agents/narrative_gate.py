"""Optional skip wrapper for narrative generation.

By default the narrative LLM always runs. When ``SKIP_NARRATIVE_BELOW_MATERIALITY``
is enabled, narrative is skipped only when there are no hierarchy insight cards
and no high-severity statistical anomalies (contract dollar/% thresholds are not
used to suppress narrative).
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, Set

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from ..utils.env_utils import parse_bool_env
from ..sub_agents.narrative_agent.agent import create_narrative_agent


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


def _hierarchy_has_insight_cards(state: dict[str, Any]) -> bool:
    """True if any level_*_analysis produced at least one hierarchy insight card."""
    for level in range(8):
        if _parse_cards(state.get(f"level_{level}_analysis")):
            return True
    return False


def _collect_known_entities_from_state(state: dict[str, Any]) -> Set[str]:
    """Entity names from hierarchy cards and statistical payloads (for grounding checks)."""
    known: set[str] = set()
    for level in range(8):
        for card in _parse_cards(state.get(f"level_{level}_analysis")):
            if not isinstance(card, dict):
                continue
            ev = card.get("evidence")
            if not isinstance(ev, dict):
                ev = {}
            for key in ("entity", "item", "item_name"):
                v = ev.get(key)
                if v and str(v).strip():
                    known.add(str(v).strip())
            v2 = card.get("item")
            if v2 and str(v2).strip():
                known.add(str(v2).strip())
    stats = _as_dict(state.get("statistical_summary"))
    for key in ("top_drivers", "anomalies"):
        rows = stats.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for k in ("item", "entity", "item_name", "item_id"):
                v = row.get(k)
                if v and str(v).strip():
                    known.add(str(v).strip())
    return known


def has_material_findings(state: dict[str, Any]) -> bool:
    """Return True when any hierarchy level produced insight cards or stats flag anomalies.

    Used only when ``SKIP_NARRATIVE_BELOW_MATERIALITY`` is true: narrative runs if the
    hierarchy (or high-severity anomalies) produced something to narrate, regardless of
    contract variance_pct / variance_absolute.
    """
    for level in range(8):
        if _parse_cards(state.get(f"level_{level}_analysis")):
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
    return parse_bool_env(os.getenv("SKIP_NARRATIVE_BELOW_MATERIALITY", "false"))


def _normalize_metric_name(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _coerce_narrative_payload(payload: Any) -> dict[str, Any]:
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


def _sanitize_narrative_payload(payload: Any, expected_metric: str, state: dict[str, Any]) -> str:
    """Ensure narrative payload is metric-consistent for current target.

    If the model returns cards for a different metric, fall back to a deterministic
    summary instead of persisting cross-metric contamination.
    """
    narrative = _coerce_narrative_payload(payload)
    cards = narrative.get("insight_cards")
    if not isinstance(cards, list):
        cards = []

    expected_norm = _normalize_metric_name(expected_metric)
    observed_metrics: list[str] = []
    mismatch_count = 0
    metric_count = 0

    for card in cards:
        if not isinstance(card, dict):
            continue
        evidence = card.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
            card["evidence"] = evidence

        observed = _normalize_metric_name(evidence.get("metric"))
        if observed:
            observed_metrics.append(observed)
            metric_count += 1
            if expected_norm and observed != expected_norm:
                mismatch_count += 1

        # Align evidence.metric to the active analysis target for downstream tools.
        if expected_metric:
            evidence["metric"] = expected_metric

    if metric_count > 0 and mismatch_count / metric_count >= 0.6:
        fallback = {
            "insight_cards": [],
            "narrative_summary": build_template_summary(state),
            "recommended_actions": [],
            "meta": {
                "narrative_sanitized": True,
                "reason": "metric_mismatch",
                "expected_metric": expected_metric,
                "observed_metrics": sorted(set(observed_metrics)),
            },
        }
        return json.dumps(fallback)

    known_entities = _collect_known_entities_from_state(state)
    if known_entities and cards:
        klow = {x.lower() for x in known_entities}
        allowed_literal = frozenset(
            {"total", "all shippers", "network", "all", "n/a"}
        )
        with_entity = 0
        unknown = 0
        for card in cards:
            if not isinstance(card, dict):
                continue
            evidence = card.get("evidence")
            if not isinstance(evidence, dict):
                continue
            ent = evidence.get("entity")
            if not ent or not str(ent).strip():
                continue
            with_entity += 1
            el = str(ent).strip().lower()
            if el in allowed_literal:
                continue
            if el not in klow:
                unknown += 1
        if with_entity and unknown / with_entity > 0.5:
            fallback = {
                "insight_cards": [],
                "narrative_summary": (
                    "Narrative entities could not be verified against hierarchy or statistical outputs; "
                    "output discarded to prevent hallucinated names."
                ),
                "recommended_actions": [],
                "meta": {
                    "narrative_sanitized": True,
                    "reason": "entity_ungrounded",
                    "expected_metric": expected_metric,
                },
            }
            return json.dumps(fallback)

    if "insight_cards" not in narrative:
        narrative["insight_cards"] = cards
    if "narrative_summary" not in narrative:
        narrative["narrative_summary"] = build_template_summary(state)
    if mismatch_count > 0:
        meta = narrative.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            narrative["meta"] = meta
        meta["narrative_sanitized"] = True
        meta["reason"] = "metric_field_aligned"
        meta["expected_metric"] = expected_metric
        meta["observed_metrics"] = sorted(set(observed_metrics))

    return json.dumps(narrative)


class ConditionalNarrativeAgent(BaseAgent):
    """Runs narrative LLM by default; optional skip when there is nothing to narrate."""

    def __init__(self, wrapped_agent: BaseAgent):
        super().__init__(name="conditional_narrative_agent")
        object.__setattr__(self, "wrapped_agent", wrapped_agent)
        object.__setattr__(self, "output_key", "narrative_results")
        object.__setattr__(self, "description", "Optional narrative skip when no hierarchy cards")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        # Allow skipping narrative entirely (e.g. during autoresearch when only brief is scored)
        if os.environ.get("NARRATIVE_AGENT_SKIP", "").lower() in ("true", "1", "yes"):
            payload = {
                "insight_cards": [],
                "narrative_summary": "Narrative skipped (NARRATIVE_AGENT_SKIP=true)",
                "recommended_actions": [],
                "meta": {"narrative_skipped": True, "reason": "env_skip"},
            }
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"narrative_results": json.dumps(payload)}),
            )
            return

        if (
            not _hierarchy_has_insight_cards(state)
            and not _has_high_severity_anomaly(state)
        ):
            payload = {
                "insight_cards": [],
                "narrative_summary": (
                    "Hierarchical analysis did not produce insight cards for this run; "
                    "narrative generation was skipped to avoid unsubstantiated entity names."
                ),
                "recommended_actions": [],
                "meta": {
                    "narrative_skipped": True,
                    "reason": "no_hierarchy_insights_for_narrative",
                },
            }
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"narrative_results": json.dumps(payload)}),
            )
            return

        if not _skip_narrative_enabled() or has_material_findings(state):
            expected_metric = str(
                state.get("current_analysis_target")
                or state.get("analysis_target")
                or ""
            )
            async for event in self.wrapped_agent.run_async(ctx):
                if (
                    event.actions
                    and isinstance(event.actions.state_delta, dict)
                    and "narrative_results" in event.actions.state_delta
                ):
                    sanitized = _sanitize_narrative_payload(
                        event.actions.state_delta.get("narrative_results"),
                        expected_metric=expected_metric,
                        state=state,
                    )
                    event.actions.state_delta["narrative_results"] = sanitized
                yield event
            return

        payload = {
            "insight_cards": [],
            "narrative_summary": build_template_summary(state),
            "recommended_actions": [],
            "meta": {
                "narrative_skipped": True,
                "reason": "no_hierarchy_insights",
            },
        }
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"narrative_results": json.dumps(payload)}),
        )


def create_conditional_narrative_agent() -> BaseAgent:
    return ConditionalNarrativeAgent(create_narrative_agent())
