"""
Cross-Metric Executive Brief Agent

Runs after all per-metric analysis pipelines complete. Reads every metric_*.md
report from the outputs directory, feeds them to an LLM, and produces a
structured one-page executive brief saved as outputs/executive_brief_<date>.md.

Spec 029: Prefers metric_*.json when available for richer digest (cross-entity
table, temporal anchors, more insight cards).

Spec 031: Writes executive_brief_input_cache.json before LLM call for iterative
refinement with different prompts/models via regenerate script.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google import genai
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import (
    EXECUTIVE_BRIEF_INSTRUCTION,
    SCOPED_BRIEF_PREAMBLE,
    load_dataset_specific_append,
    load_prompt_variant,
)
from ...utils import parse_bool_env
from .prompt_utils import (
    _build_weather_context_block,
    _format_analysis_period,
    _format_brief,
    _format_brief_with_fallback,
    _write_executive_brief_cache,
)
from .report_utils import (
    _build_digest,
    _build_digest_from_json,
    _collect_metric_json_data,
    _collect_metric_reports,
)
from .scope_utils import (
    _build_scoped_digest,
    _discover_level_entities,
    _load_hierarchy_level_mapping,
    _sanitize_entity_name,
)


def _ensure_card_titles(card_list: list[dict[str, Any]] | None, prefix: str) -> None:
    if not isinstance(card_list, list):
        return
    for idx, card in enumerate(card_list, 1):
        if not isinstance(card, dict):
            continue
        title = (card.get("title") or "").strip()
        if title:
            continue
        fallback = (
            card.get("item")
            or card.get("item_name")
            or card.get("level_name")
            or card.get("dimension_value")
            or card.get("what_changed")
            or prefix
        )
        fallback = str(fallback).strip() or prefix
        suffix = f" (Insight {idx})" if idx > 1 else ""
        card["title"] = f"{prefix}: {fallback}{suffix}" if prefix and not fallback.lower().startswith(prefix.lower()) else f"{fallback}{suffix}".strip()


def _ensure_block_titles(block: Any, prefix: str) -> Any:
    was_str = isinstance(block, str)
    data = block
    if was_str:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            return block
    if isinstance(data, dict):
        _ensure_card_titles(data.get("insight_cards"), prefix)
    return json.dumps(data) if was_str else data


def _backfill_missing_titles(json_data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for metric_name, payload in json_data.items():
        prefix = str(metric_name).strip() or "Insight"
        narrative = payload.get("narrative_results")
        if narrative:
            payload["narrative_results"] = _ensure_block_titles(narrative, prefix)
        hier = payload.get("hierarchical_analysis")
        if isinstance(hier, dict):
            for key in list(hier.keys()):
                block = hier.get(key)
                if isinstance(block, (dict, str)):
                    hier[key] = _ensure_block_titles(block, f"{prefix} {key}")
            indep = hier.get("independent_level_results")
            if isinstance(indep, dict):
                for key in list(indep.keys()):
                    block = indep.get(key)
                    if isinstance(block, (dict, str)):
                        indep[key] = _ensure_block_titles(block, f"{prefix} {key}")
        analysis = payload.get("analysis")
        if isinstance(analysis, dict):
            _ensure_card_titles(analysis.get("insight_cards"), prefix)
            alert_block = analysis.get("alert_scoring") or {}
            if isinstance(alert_block, dict):
                _ensure_card_titles(alert_block.get("top_alerts"), f"{prefix} Alert")
    return json_data


def _build_brief_response_schema() -> types.Schema:
    insight_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING),
            "details": types.Schema(type=types.Type.STRING),
        },
        required=["title", "details"],
    )
    section_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING),
            "content": types.Schema(type=types.Type.STRING),
            "insights": types.Schema(
                type=types.Type.ARRAY,
                items=insight_schema,
            ),
        },
        required=["title"],
    )
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "header": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "title": types.Schema(type=types.Type.STRING),
                    "summary": types.Schema(type=types.Type.STRING),
                },
                required=["title", "summary"],
            ),
            "body": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "sections": types.Schema(
                        type=types.Type.ARRAY,
                        min_items=1,
                        items=section_schema,
                    ),
                },
                required=["sections"],
            ),
        },
        required=["header", "body"],
    )


EXECUTIVE_BRIEF_RESPONSE_SCHEMA = _build_brief_response_schema()


def _derive_scope_level_labels(contract: Any | None) -> dict[int, str]:
    labels: dict[int, str] = {}
    if not contract:
        return labels
    hierarchies = getattr(contract, "hierarchies", None) or []
    preferred = None
    for hierarchy in hierarchies:
        name = str(getattr(hierarchy, "name", "")).lower()
        if name == "full_hierarchy":
            preferred = hierarchy
            break
    if preferred is None and hierarchies:
        preferred = hierarchies[0]
    if not preferred:
        return labels
    level_names = getattr(preferred, "level_names", {}) or {}
    for raw_idx, label in level_names.items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if idx == 0:
            continue
        labels[idx] = str(label)
    return labels



def _format_instruction(template: str, **fields: str) -> str:
    """Safely render the executive-brief prompt with literal braces intact."""
    placeholders = {key: f"<<{key.upper()}_PLACEHOLDER>>" for key in fields}
    safe = template
    for key, token in placeholders.items():
        safe = safe.replace(f"{{{key}}}", token)
    safe = safe.replace("{", "{{").replace("}", "}}")
    for key, token in placeholders.items():
        safe = safe.replace(token, f"{{{key}}}")
    return safe.format(**fields)


async def _llm_generate_brief(
    model_name: str,
    instruction: str,
    user_message: str,
    thinking_config: Any,
    digest: str = "",
) -> tuple[dict, str]:
    """Call the LLM to generate a brief JSON. Returns (brief_data_dict, brief_markdown)."""
    import asyncio

    config = types.GenerateContentConfig(
        system_instruction=instruction,
        response_modalities=["TEXT"],
        response_mime_type="application/json",
        response_schema=EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
        temperature=0.05,
        thinking_config=thinking_config,
    )
    loop = asyncio.get_running_loop()
    raw: str | None = None
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            client = genai.Client()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=model_name,
                        contents=user_message,
                        config=config,
                    ),
                ),
                timeout=300.0,
            )
            raw = response.text.strip()
            break
        except Exception as attempt_err:
            last_err = attempt_err
            print(f"[BRIEF] Attempt {attempt}/3 failed: {attempt_err}. Retrying in 5s...")
            if attempt < 3:
                await asyncio.sleep(5)

    if raw is None:
        raise last_err  # type: ignore[misc]

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    brief_data = json.loads(raw)
    return brief_data, _format_brief_with_fallback(brief_data, digest)




class CrossMetricExecutiveBriefAgent(BaseAgent):
    """Synthesizes all per-metric analysis reports into a single executive brief."""

    def __init__(self) -> None:
        super().__init__(name="executive_brief_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import asyncio

        print("\n" + "=" * 80)
        print("[BRIEF] CrossMetricExecutiveBriefAgent starting")
        print("=" * 80)

        run_dir = os.getenv("DATA_ANALYST_OUTPUT_DIR")
        outputs_dir = Path(run_dir).resolve() if run_dir else Path("outputs").resolve()
        reports = _collect_metric_reports(outputs_dir)

        extracted_targets = ctx.session.state.get("extracted_targets") or []
        if extracted_targets:
            requested = {str(t).strip().replace(" ", "_").lower() for t in extracted_targets}
            reports = {k: v for k, v in reports.items() if k.replace(" ", "_").lower() in requested}
            if reports:
                print(f"[BRIEF] Filtered to {len(reports)} requested metric(s): {', '.join(reports.keys())}")

        if not reports:
            if extracted_targets:
                print("[BRIEF] No metric reports found for requested metric(s). Skipping.")
            else:
                print("[BRIEF] No metric reports found in outputs/. Skipping.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        print(f"[BRIEF] Found {len(reports)} metric report(s): {', '.join(reports.keys())}")

        timeframe = ctx.session.state.get("timeframe", {})
        period_end = timeframe.get("end") or ctx.session.state.get("primary_query_end_date")
        if not period_end:
            first_content = next(iter(reports.values()), "")
            match = re.search(r"\d{4}-\d{2}-\d{2}", first_content)
            period_end = match.group(0) if match else datetime.now().strftime("%Y-%m-%d")
        analysis_period = ctx.session.state.get("analysis_period") or _format_analysis_period(
            period_end, ctx.session.state.get("dataset_contract")
        )
        print(f"[BRIEF] Analysis period: {analysis_period}")

        json_data = _collect_metric_json_data(outputs_dir)
        if extracted_targets:
            requested = {str(t).strip().replace(" ", "_").lower() for t in extracted_targets}
            json_data = {k: v for k, v in json_data.items() if k.replace(" ", "_").lower() in requested}
        if json_data:
            json_data = _backfill_missing_titles(json_data)

        focus_modes = ctx.session.state.get("analysis_focus") or []
        custom_focus = ctx.session.state.get("custom_focus") or ""
        focus_lines = []
        if focus_modes:
            focus_lines.append(f"- Focus modes: {', '.join(focus_modes)}")
        if custom_focus:
            focus_lines.append(f"- Custom directive: {custom_focus}")
        focus_block = "\n".join(focus_lines)

        use_json = parse_bool_env(os.environ.get("EXECUTIVE_BRIEF_USE_JSON", "true"))
        if use_json and json_data:
            digest = _build_digest_from_json(json_data, reports)
            print(f"[BRIEF] Using JSON-backed digest ({len(json_data)} metrics)")
        else:
            digest = _build_digest(reports)
            print("[BRIEF] Using markdown-only digest")

        drill_levels = 0
        max_scope_entities = 10
        min_scope_share_of_total = 0.0
        output_format = "pdf"

        try:
            import yaml

            config_path = Path(__file__).resolve().parents[3] / "config" / "report_config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    report_cfg = yaml.safe_load(f) or {}
                    eb_cfg = report_cfg.get("executive_brief", {})
                    drill_levels = eb_cfg.get("drill_levels", 0)
                    max_scope_entities = eb_cfg.get("max_scope_entities", 10)
                    min_scope_share_of_total = float(eb_cfg.get("min_scope_share_of_total", min_scope_share_of_total))
                    output_format = eb_cfg.get("output_format", "pdf")
        except Exception as e:
            print(f"[BRIEF] Warning: Failed to load report_config.yaml: {e}")

        contract = ctx.session.state.get("dataset_contract")
        if contract and getattr(contract, "reporting", None):
            reporting_cfg = contract.reporting
            drill_levels = reporting_cfg.executive_brief_drill_levels
            max_scope_entities = reporting_cfg.max_scope_entities
            min_scope_share_of_total = float(getattr(reporting_cfg, "min_scope_share_of_total", min_scope_share_of_total) or 0.0)
            output_format = reporting_cfg.output_format
            print(f"[BRIEF] Using reporting settings from contract: {contract.name}")

        session_drill = ctx.session.state.get("executive_brief_drill_levels")
        if session_drill is not None:
            try:
                drill_levels = int(session_drill)
            except (ValueError, TypeError):
                pass

        env_drill = os.environ.get("EXECUTIVE_BRIEF_DRILL_LEVELS")
        if env_drill is not None:
            try:
                drill_levels = int(env_drill)
                print(f"[BRIEF] Overriding drill_levels={drill_levels} from env")
            except (ValueError, TypeError):
                pass

        env_max_scope = os.environ.get("EXECUTIVE_BRIEF_MAX_SCOPE_ENTITIES")
        if env_max_scope is not None:
            try:
                max_scope_entities = int(env_max_scope)
                print(f"[BRIEF] Overriding max_scope_entities={max_scope_entities} from env")
            except (ValueError, TypeError):
                pass

        env_min_scope_share = os.environ.get("EXECUTIVE_BRIEF_MIN_SCOPE_SHARE")
        if env_min_scope_share is not None:
            try:
                min_scope_share_of_total = float(env_min_scope_share)
                print(f"[BRIEF] Overriding min_scope_share_of_total={min_scope_share_of_total:.4f} from env")
            except (ValueError, TypeError):
                pass

        # Build contract-driven context for the prompt
        contract = ctx.session.state.get("dataset_contract")
        dataset_name = getattr(contract, "display_name", getattr(contract, "name", "the dataset")) if contract else "the dataset"
        dataset_desc = getattr(contract, "description", "") if contract else ""
        contract_context = f"\nDataset: {dataset_name}."
        if dataset_desc:
            contract_context += f" {dataset_desc.strip()}"

        instruction = _format_instruction(
            EXECUTIVE_BRIEF_INSTRUCTION,
            metric_count=len(reports),
            analysis_period=analysis_period,
            scope_preamble=focus_block,
            dataset_specific_append=load_dataset_specific_append() + contract_context,
            prompt_variant_append=load_prompt_variant(os.environ.get("EXECUTIVE_BRIEF_PROMPT_VARIANT", "default")),
        )
        weather_block = _build_weather_context_block(ctx.session.state.get("weather_context"))

        temporal_grain = ctx.session.state.get("temporal_grain", "unknown")
        brief_temporal_context = {
            "reference_period_end": period_end,
            "temporal_grain": temporal_grain,
            "analysis_period": analysis_period,
            "period_unit": "week" if temporal_grain == "weekly" else "month",
            "default_comparison_basis": (
                "vs prior week (WoW)" if temporal_grain == "weekly" else "vs prior month (MoM)"
            ),
            "comparison_priority_order": (
                [
                    "current week vs prior week (WoW)",
                    "current week vs rolling 4-week average",
                    "other supported comparisons (lower priority)",
                ]
                if temporal_grain == "weekly"
                else [
                    "current month vs prior month (MoM)",
                    "current month vs rolling 3-month average",
                    "current month vs same month prior year (YoY)",
                    "other supported comparisons (lower priority)",
                ]
            ),
            "comparison_requirement": (
                "Every comparative claim must include its explicit baseline in the same sentence."
            ),
        }

        focus_preamble_text = f"FOCUS_DIRECTIVES:\n{focus_block}\n\n" if focus_block else ""

        user_message = (
            f"{focus_preamble_text}"
            f"BRIEF_TEMPORAL_CONTEXT (MANDATORY GROUNDING):\n"
            f"{json.dumps(brief_temporal_context, indent=2)}\n\n"
            f"Use the above 'reference_period_end' as the date in your JSON 'subject'.\n\n"
            f"Here are the individual metric analysis summaries for {analysis_period}.\n\n"
            f"{digest}\n\n"
            f"{weather_block}"
            "Generate the executive brief JSON as instructed."
        )

        metric_names = sorted(reports.keys())
        model_name = get_agent_model("executive_brief_agent")
        thinking_config = get_agent_thinking_config("executive_brief_agent")

        _write_executive_brief_cache(
            outputs_dir=outputs_dir,
            digest=digest + weather_block,
            period_end=period_end,
            analysis_period=analysis_period,
            metric_names=metric_names,
            timeframe=timeframe if isinstance(timeframe, dict) else {},
            weather_context=ctx.session.state.get("weather_context"),
            dataset=ctx.session.state.get("dataset"),
        )

        print(f"[BRIEF] Sending digest ({len(digest)} chars) to LLM...")

        try:
            _, brief_md = await _llm_generate_brief(
                model_name=model_name,
                instruction=instruction,
                user_message=user_message,
                thinking_config=thinking_config,
                digest=digest,
            )

            brief_filename = "brief.md" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else f"executive_brief_{period_end}.md"
            brief_path = outputs_dir / brief_filename
            brief_path.write_text(brief_md, encoding="utf-8")
            print(f"[BRIEF] Saved executive brief to {brief_filename}")
            print(f"[BRIEF] File size: {brief_path.stat().st_size} bytes")

            print("\n" + "=" * 80)
            print("EXECUTIVE BRIEF")
            print("=" * 80)
            print(brief_md)
            print("=" * 80 + "\n")

            scoped_briefs: dict[str, dict[str, str]] = {}
            scoped_digests_map: dict[str, str] = {}
            scope_level_labels = _derive_scope_level_labels(contract)

            if drill_levels >= 1 and json_data:
                print(f"[BRIEF] Drill levels={drill_levels}: generating scoped briefs")
                for level in range(1, min(drill_levels, 2) + 1):
                    entities = _discover_level_entities(
                        json_data,
                        level,
                        min_share_of_total=min_scope_share_of_total,
                    )
                    if level == 2:
                        entities = entities[:max_scope_entities]
                    level_name = scope_level_labels.get(level, f"Level {level}")
                    print(f"[BRIEF] Level {level} ({level_name}): {len(entities)} entities: {', '.join(entities)}")

                    hierarchy_map = _load_hierarchy_level_mapping(json_data, level, level + 1)
                    if hierarchy_map:
                        total_children = sum(len(v) for v in hierarchy_map.values())
                        print(
                            f"[BRIEF] Hierarchy mapping loaded ({total_children} children across {len(hierarchy_map)} parents)"
                        )
                    else:
                        print("[BRIEF] No hierarchy mapping found — using Strategy A fallback")

                    for entity in entities:
                        scope_children = set(hierarchy_map.get(entity, [])) if hierarchy_map else None
                        scoped_digest = _build_scoped_digest(
                            json_data,
                            reports,
                            entity,
                            level,
                            analysis_period,
                            scope_children=scope_children,
                        )
                        scoped_digests_map[entity] = scoped_digest

                        scope_preamble = SCOPED_BRIEF_PREAMBLE.format(
                            scope_entity=entity,
                            scope_level_name=level_name.lower(),
                        )
                        scoped_instruction = _format_instruction(
                            EXECUTIVE_BRIEF_INSTRUCTION,
                            metric_count=len(reports),
                            analysis_period=analysis_period,
                            scope_preamble=scope_preamble,
                            dataset_specific_append=load_dataset_specific_append(),
                            prompt_variant_append=load_prompt_variant(
                                os.environ.get("EXECUTIVE_BRIEF_PROMPT_VARIANT", "default")
                            ),
                        )
                        scoped_user_message = (
                            f"BRIEF_TEMPORAL_CONTEXT (MANDATORY GROUNDING):\n"
                            f"{json.dumps(brief_temporal_context, indent=2)}\n\n"
                            f"Use the above 'reference_period_end' as the date in your JSON 'subject'.\n\n"
                            f"Here are the individual metric analysis summaries for {analysis_period}, scoped to {entity}.\n\n"
                            f"{scoped_digest}\n\n"
                            "Generate the executive brief JSON as instructed. Focus exclusively on this scope."
                        )
                        print(f"[BRIEF] Generating scoped brief for {entity} ({level_name})...")
                        try:
                            _, scoped_brief_md = await _llm_generate_brief(
                                model_name=model_name,
                                instruction=scoped_instruction,
                                user_message=scoped_user_message,
                                thinking_config=thinking_config,
                                digest=scoped_digest,
                            )
                            safe_entity = _sanitize_entity_name(entity)
                            scoped_filename = (
                                "brief_" + safe_entity + ".md"
                                if os.getenv("DATA_ANALYST_OUTPUT_DIR")
                                else f"executive_brief_{period_end}_{safe_entity}.md"
                            )
                            scoped_path = outputs_dir / scoped_filename
                            scoped_path.write_text(scoped_brief_md, encoding="utf-8")
                            print(f"[BRIEF] Saved scoped brief for {entity} to {scoped_filename}")
                            scoped_briefs[entity] = {
                                "path": str(scoped_path),
                                "content": scoped_brief_md,
                                "level": level,
                                "level_name": level_name,
                                "bookmark_label": f"{entity} ({level_name})",
                            }
                        except Exception as scope_err:
                            print(f"[BRIEF] ERROR generating scoped brief for {entity}: {scope_err}")

                if scoped_digests_map:
                    _write_executive_brief_cache(
                        outputs_dir=outputs_dir,
                        digest=digest + weather_block,
                        period_end=period_end,
                        analysis_period=analysis_period,
                        metric_names=metric_names,
                        timeframe=timeframe if isinstance(timeframe, dict) else {},
                        weather_context=ctx.session.state.get("weather_context"),
                        dataset=ctx.session.state.get("dataset"),
                        drill_levels=drill_levels,
                        scoped_digests=scoped_digests_map,
                    )

            env_format = os.environ.get("EXECUTIVE_BRIEF_OUTPUT_FORMAT")
            if env_format:
                output_format = env_format.lower()

            pdf_path: Path | None = None
            html_path: Path | None = None

            from .pdf_renderer import BriefPage

            network_label = f"Network — {period_end}"
            pages: list[BriefPage] = [
                BriefPage(bookmark_label=network_label, markdown_content=brief_md, level=0)
            ]
            for info in scoped_briefs.values():
                pages.append(
                    BriefPage(
                        bookmark_label=info.get("bookmark_label", "Scoped"),
                        markdown_content=info["content"],
                        level=info.get("level", 1),
                    )
                )

            if output_format in ("pdf", "both"):
                try:
                    from .pdf_renderer import render_briefs_to_pdf

                    pdf_filename = "brief.pdf" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else f"executive_brief_{period_end}.pdf"
                    pdf_path = render_briefs_to_pdf(pages, outputs_dir / pdf_filename, period_end)
                except Exception as pdf_err:
                    print(f"[BRIEF] PDF rendering error (non-fatal): {pdf_err}")

            if output_format in ("html", "both"):
                try:
                    from .html_renderer import render_briefs_to_html

                    html_filename = "brief.html" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else f"executive_brief_{period_end}.html"
                    html_path = render_briefs_to_html(pages, outputs_dir / html_filename, period_end)
                except Exception as html_err:
                    print(f"[BRIEF] HTML rendering error (non-fatal): {html_err}")

            state_delta: dict[str, Any] = {
                "executive_brief": brief_md,
                "executive_brief_path": str(brief_path),
            }
            if scoped_briefs:
                state_delta["scoped_briefs"] = scoped_briefs
            if pdf_path:
                state_delta["executive_brief_pdf"] = str(pdf_path)
            if html_path:
                state_delta["executive_brief_html"] = str(html_path)

            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta=state_delta),
            )

        except asyncio.TimeoutError:
            print("[BRIEF] TIMEOUT: LLM call exceeded 300s. Executive brief not generated.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
        except json.JSONDecodeError as exc:
            print(f"[BRIEF] JSON parse error: {exc}.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
        except Exception as exc:  # noqa: BLE001
            import traceback

            print(f"[BRIEF] ERROR: {exc}")
            traceback.print_exc()
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())

        print("\n[BRIEF] CrossMetricExecutiveBriefAgent complete")
