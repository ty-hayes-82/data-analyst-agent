from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, Optional, Set, Tuple

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from .settings import INDEPENDENT_LEVEL_ANALYSIS, INDEPENDENT_LEVEL_MAX_CARDS


class IndependentLevelAnalysisAgent(BaseAgent):
    """Multi-pass flat scan agent for optional level-by-level analysis."""

    def __init__(self) -> None:
        super().__init__(name="independent_level_analysis_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if not INDEPENDENT_LEVEL_ANALYSIS:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        max_depth = ctx.session.state.get("max_drill_depth", 5)
        levels_analyzed = ctx.session.state.get("levels_analyzed", [])

        pass0_found: Set[Tuple[int, str]] = set()
        for lvl in levels_analyzed:
            lvl_data = ctx.session.state.get(f"level_{lvl}_analysis")
            if not lvl_data:
                continue
            try:
                parsed = json.loads(lvl_data) if isinstance(lvl_data, str) else lvl_data
                for card in parsed.get("insight_cards", []):
                    title = card.get("title", "")
                    if ": " in title:
                        entity = title.split(": ", 1)[1].strip()
                        pass0_found.add((lvl, entity.lower()))
            except (json.JSONDecodeError, AttributeError):
                continue

        print(
            f"\n[IndependentLevelAnalysis] Starting flat scans for levels 1..{max_depth} "
            f"(Pass 0 surfaced {len(pass0_found)} entity/level pairs)"
        )

        import asyncio

        async def _run_single_scan(start_level: int) -> Optional[Tuple[int, Dict[str, Any]]]:
            print(
                "[IndependentLevelAnalysis] Pass {start_level}: flat scan starting at Level "
                f"{start_level}"
            )
            try:
                from ..hierarchy_variance_agent.tools.compute_level_statistics import (
                    compute_level_statistics,
                )
                from ..hierarchy_variance_agent.tools.format_insight_cards import (
                    format_hierarchy_insight_cards,
                )

                stats_str = await compute_level_statistics(level=start_level)
                stats = json.loads(stats_str) if isinstance(stats_str, str) else stats_str

                if "error" in stats:
                    print(
                        f"  -> Level {start_level} skipped: {stats.get('message', stats['error'])}"
                    )
                    return None

                raw_cards = format_hierarchy_insight_cards(
                    level_stats=stats, discovery_method="independent_scan"
                )
                all_cards = raw_cards.get("insight_cards", [])

                new_cards = []
                for card in all_cards:
                    title = card.get("title", "")
                    entity = title.split(": ", 1)[-1].strip() if ": " in title else title
                    card_level = stats.get("level", start_level)
                    if (card_level, entity.lower()) not in pass0_found:
                        card["discovery_method"] = "independent_scan"
                        new_cards.append(card)

                new_cards = new_cards[:INDEPENDENT_LEVEL_MAX_CARDS]

                result = {
                    "insight_cards": new_cards,
                    "total_variance_dollar": raw_cards.get("total_variance_dollar", 0.0),
                    "level": stats.get("level", start_level),
                    "level_name": stats.get("level_name", f"Level {start_level}"),
                    "is_last_level": stats.get("is_last_level", False),
                    "pass_type": "independent_scan",
                    "start_level": start_level,
                    "total_candidates": raw_cards.get("total_candidates", 0),
                    "new_cards_after_dedup": len(new_cards),
                }
                print(
                    f"  -> Level {start_level} complete: {len(all_cards)} candidates, "
                    f"{len(new_cards)} net-new after dedup"
                )
                return start_level, result

            except Exception as exc:  # noqa: BLE001
                print(f"  -> Level {start_level} flat scan failed: {exc}")
                return None

        scan_tasks = [_run_single_scan(lvl) for lvl in range(1, max_depth + 1)]
        scan_results = await asyncio.gather(*scan_tasks)

        state_delta: Dict[str, Any] = {}
        for res in scan_results:
            if not res:
                continue
            start_lvl, result_obj = res
            state_key = f"independent_level_{start_lvl}_analysis"
            state_delta[state_key] = result_obj
            ctx.session.state[state_key] = result_obj

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )
