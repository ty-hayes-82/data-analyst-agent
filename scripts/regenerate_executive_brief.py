"""
Regenerate the executive brief from cached metric reports in outputs/.

Reads all metric_*.md files (or a subset via --metrics), builds the same digest
used by CrossMetricExecutiveBriefAgent, calls the LLM, and writes
executive_brief_<YYYY-MM-DD>.md.

Spec 029: --use-json prefers metric_*.json when available (cross-entity table,
temporal anchors). --digest-only prints the digest without calling the LLM.

Spec 030: When WEATHER_CONTEXT_ENABLED=true, runs WeatherContextAgent (ADK agent
grounded in Google Search) and appends WEATHER CONTEXT block to the digest.

Spec 031: --from-cache uses executive_brief_input_cache.json; --cache-only writes
cache without LLM; --prompt-variant and --model for iterative refinement.

Spec 032: --drill-levels N generates one scoped brief per entity at each hierarchy
level (mirrors EXECUTIVE_BRIEF_DRILL_LEVELS env var). Cache upgraded to v2 with
scoped_digests when drill levels > 0.

Usage:
    python scripts/regenerate_executive_brief.py
    python scripts/regenerate_executive_brief.py --week-ending 2026-02-14
    python scripts/regenerate_executive_brief.py --from-cache
    python scripts/regenerate_executive_brief.py --from-cache --prompt-variant actionable --model gemini-3-flash-preview
    python scripts/regenerate_executive_brief.py --cache-only
    python scripts/regenerate_executive_brief.py --digest-only
    python scripts/regenerate_executive_brief.py --drill-levels 1
    python scripts/regenerate_executive_brief.py --drill-levels 1 --from-cache
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _setup_env() -> None:
    """Load .env if present."""
    try:
        from dotenv import load_dotenv

        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass


def _collect_metric_reports(outputs_dir: Path) -> dict[str, str]:
    """Read all metric_*.md files and return {metric_name: markdown_content}."""
    reports = {}
    for md_file in sorted(outputs_dir.glob("metric_*.md")):
        name = md_file.stem.replace("metric_", "").replace("_", " ").replace("-", "/")
        content = md_file.read_text(encoding="utf-8", errors="replace")
        reports[name] = content
    return reports


def _extract_executive_summary(markdown: str) -> str:
    """Pull just the Executive Summary section from a metric report."""
    lines = markdown.splitlines()
    in_section = False
    section_lines = []
    for line in lines:
        if line.startswith("## Executive Summary"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and line != "## Executive Summary":
                break
            section_lines.append(line)
    return "\n".join(section_lines).strip()


def _extract_insight_cards(markdown: str, max_cards: int = 5) -> str:
    """Pull up to max_cards insight card blocks from a metric report."""
    lines = markdown.splitlines()
    in_section = False
    card_lines: list[str] = []
    card_count = 0

    for line in lines:
        if line.startswith("## Insight Cards"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and "Insight Cards" not in line:
                break
            if line.startswith("### "):
                card_count += 1
                if card_count > max_cards:
                    break
            card_lines.append(line)

    return "\n".join(card_lines).strip()


def _build_digest(reports: dict[str, str]) -> str:
    """Build a compact digest of all metric reports for the LLM prompt."""
    parts = []
    for metric_name, content in reports.items():
        summary = _extract_executive_summary(content)
        cards = _extract_insight_cards(content, max_cards=4)
        section = (
            f"=== {metric_name.upper()} ===\n"
            f"SUMMARY:\n{summary}\n\n"
            f"TOP INSIGHTS:\n{cards}\n"
        )
        parts.append(section)
    return "\n\n".join(parts)


def _format_brief(brief: dict) -> str:
    """Render the LLM JSON response as clean markdown."""
    subject = brief.get("subject", "Weekly Performance Brief")
    opening = brief.get("opening") or brief.get("summary", "")

    # New email-style fields
    top_insights = brief.get("top_operational_insights", [])
    network_snapshot = brief.get("network_snapshot", "")
    focus_for_next_week = brief.get("focus_for_next_week", "")
    scope_summary = brief.get("scope_summary") or brief.get("regional_summary", "")
    child_entity_label = brief.get("child_entity_label", "Child Entity")
    child_entity_insights = brief.get("child_entity_insights") or brief.get("terminal_insights", [])
    structural_insights = brief.get("structural_insights") or brief.get("regional_insight", [])
    leadership_question = brief.get("leadership_question", "")
    signoff_name = brief.get("signoff_name", "Ty")

    # Legacy fallback fields
    going_well = brief.get("whats_going_well", [])
    masking = brief.get("whats_masking_the_picture", [])
    concern = brief.get("primary_concern", "")
    bottom_line = brief.get("bottom_line", "")

    is_scoped_deep_dive = bool(scope_summary or child_entity_insights or structural_insights or leadership_question)
    lines = [f"**Subject: {subject}**", "", "Team,", ""]

    if opening:
        lines += [opening, ""]

    if is_scoped_deep_dive:
        if scope_summary:
            lines += ["**Scope Summary**", "", scope_summary, ""]

        if child_entity_insights:
            lines += [f"**{child_entity_label} Insights**", ""]
            for child_data in child_entity_insights:
                if not isinstance(child_data, dict):
                    continue
                entity_name = str(child_data.get("entity") or child_data.get("terminal", "")).strip()
                entity_analysis = str(child_data.get("analysis", "")).strip()
                key_takeaway = str(child_data.get("key_takeaway", "")).strip()

                if entity_name:
                    lines += [f"**{entity_name}**", ""]
                if entity_analysis:
                    lines += [entity_analysis, ""]
                if key_takeaway:
                    lines += [f"Key takeaway: {key_takeaway}", ""]

        if structural_insights:
            lines += ["**Structural Insights**", ""]
            for item in structural_insights:
                lines.append(f"- {item}")
            lines.append("")

        if leadership_question:
            lines += ["**Leadership Question**", "", leadership_question, ""]
    else:
        if top_insights:
            lines += ["**Top Operational Insights**", ""]
            for idx, insight in enumerate(top_insights, start=1):
                if isinstance(insight, dict):
                    title = str(insight.get("title", "")).strip()
                    detail = str(insight.get("detail", "")).strip()
                else:
                    title = ""
                    detail = str(insight).strip()

                lines += [f"{idx}. {title or f'Insight {idx}'}"]
                if detail:
                    lines += [detail, ""]
                else:
                    lines.append("")
        else:
            lines += ["**Top Operational Insights**", ""]
            combined = list(going_well) + list(masking)
            for idx, item in enumerate(combined[:4], start=1):
                lines += [f"{idx}. Insight {idx}", str(item), ""]

        if network_snapshot:
            lines += ["**Network Snapshot**", "", network_snapshot, ""]
        elif bottom_line:
            lines += ["**Network Snapshot**", "", bottom_line, ""]

        if focus_for_next_week:
            lines += ["**Focus for next week**", "", focus_for_next_week, ""]
        elif concern:
            lines += ["**Focus for next week**", "", concern, ""]

    lines += [
        "Best,",
        signoff_name,
        "",
        "---",
        f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by the Cross-Metric Executive Brief Agent*",
    ]
    return "\n".join(lines)


def _run_weather_context_agent(outputs_dir: Path) -> str:
    """Run WeatherContextAgent to get weather context. Returns WEATHER CONTEXT block or "".
    Weather agent reads from Path('outputs').resolve(), so we chdir to outputs_dir.parent temporarily.
    """
    import asyncio
    import os
    from data_analyst_agent.sub_agents.weather_context_agent import root_agent as weather_agent
    from data_analyst_agent.sub_agents.executive_brief_agent.agent import _build_weather_context_block
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.runners import Runner
    from google.genai import types

    async def _run() -> str:
        session_service = InMemorySessionService()
        runner = Runner(
            app_name="regenerate_brief",
            agent=weather_agent,
            session_service=session_service,
        )
        session = await session_service.create_session(
            app_name="regenerate_brief",
            user_id="regenerate_script",
        )
        content = types.Content(role="user", parts=[types.Part.from_text(text="Run weather check")])
        weather_context = None
        async for event in runner.run_async(
            user_id="regenerate_script",
            session_id=session.id,
            new_message=content,
        ):
            if getattr(event, "actions", None) and event.actions.state_delta:
                weather_context = event.actions.state_delta.get("weather_context")
        return _build_weather_context_block(weather_context) if weather_context else ""

    try:
        orig = os.environ.get("WEATHER_OUTPUTS_DIR")
        try:
            os.environ["WEATHER_OUTPUTS_DIR"] = str(outputs_dir)
            return asyncio.run(_run())
        finally:
            if orig is not None:
                os.environ["WEATHER_OUTPUTS_DIR"] = orig
            elif "WEATHER_OUTPUTS_DIR" in os.environ:
                del os.environ["WEATHER_OUTPUTS_DIR"]
    except Exception as e:
        print(f"[regenerate] Weather agent failed: {e}. Proceeding without weather context.")
        return ""


def _load_cache(outputs_dir: Path) -> dict | None:
    """Load executive_brief_input_cache.json if present. Returns None if missing or invalid."""
    cache_path = outputs_dir / "executive_brief_input_cache.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(
    outputs_dir: Path,
    digest: str,
    week_ending: str,
    analysis_period: str,
    metrics: list[str],
    timeframe: dict,
    weather_context: dict | None,
    dataset: str = "unknown",
    drill_levels: int = 0,
    scoped_digests: dict | None = None,
) -> None:
    """Write executive_brief_input_cache.json.

    Version 1: network-only (drill_levels == 0).
    Version 2: includes drill_levels and scoped_digests dict (Spec 032).
    """
    version = 2 if (drill_levels > 0 or scoped_digests) else 1
    cache: dict = {
        "version": version,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": dataset,
        "period_end": week_ending,
        "analysis_period": analysis_period,
        "metrics": metrics,
        "metric_count": len(metrics),
        "timeframe": timeframe,
        "digest": digest,
        "weather_context": weather_context,
    }
    if version == 2:
        cache["drill_levels"] = drill_levels
        cache["scoped_digests"] = scoped_digests or {}
    cache_path = outputs_dir / "executive_brief_input_cache.json"
    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(f"[regenerate] Wrote cache to {cache_path.name} (v{version})")


def _infer_week_ending(reports: dict[str, str]) -> str:
    """Infer week ending date from the first report's header or period."""
    first_content = next(iter(reports.values()), "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", first_content)
    return match.group(0) if match else datetime.now().strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate executive brief from cached metric reports in outputs/."
    )
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=PROJECT_ROOT / "outputs",
        help="Directory containing metric_*.md files (default: outputs/)",
    )
    parser.add_argument(
        "--week-ending",
        type=str,
        default=None,
        help="Target week ending date (YYYY-MM-DD). Auto-inferred from reports if omitted.",
    )
    parser.add_argument(
        "--metrics",
        type=str,
        default=None,
        help="Comma-separated metric names to include (default: all metric reports)",
    )
    parser.add_argument(
        "--use-json",
        action="store_true",
        help="Prefer metric_*.json for digest (cross-entity table, temporal anchors)",
    )
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="Print digest to stdout and exit without calling LLM",
    )
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Load digest from executive_brief_input_cache.json (fails if cache missing)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Always build digest from outputs, ignore cache",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Build digest, write cache, and exit without calling LLM",
    )
    parser.add_argument(
        "--prompt-variant",
        type=str,
        default="default",
        metavar="NAME",
        help="Prompt variant (default, actionable). Loads from config/prompts/executive_brief/",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        metavar="MODEL",
        help="Override LLM model (e.g. gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--drill-levels",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Generate scoped briefs for N hierarchy levels below network "
            "(0=network only, 1=+regions, 2=+terminals). "
            "Overrides EXECUTIVE_BRIEF_DRILL_LEVELS env var when set."
        ),
    )
    parser.add_argument(
        "--output-format",
        type=str,
        default=None,
        metavar="FORMAT",
        choices=["md", "pdf", "both"],
        help=(
            "Output format for briefs: md = markdown only, pdf = markdown + combined PDF "
            "(default), both = alias for pdf. Overrides EXECUTIVE_BRIEF_OUTPUT_FORMAT env var."
        ),
    )
    args = parser.parse_args()

    _setup_env()

    # Resolve drill_levels: CLI arg overrides env var (FR-4.1)
    if args.drill_levels is not None:
        drill_levels = max(0, args.drill_levels)
    else:
        try:
            drill_levels = int(os.environ.get("EXECUTIVE_BRIEF_DRILL_LEVELS", "0"))
        except (ValueError, TypeError):
            drill_levels = 0

    # Resolve output_format: CLI arg overrides env var (Spec 033)
    if args.output_format is not None:
        output_format = args.output_format.lower()
    else:
        output_format = os.environ.get("EXECUTIVE_BRIEF_OUTPUT_FORMAT", "pdf").lower()
    if output_format not in ("md", "pdf", "both"):
        output_format = "pdf"
    try:
        max_scope_entities = int(os.environ.get("EXECUTIVE_BRIEF_MAX_SCOPE_ENTITIES", "10"))
    except (ValueError, TypeError):
        max_scope_entities = 10

    outputs_dir = args.outputs_dir.resolve()
    if not outputs_dir.exists():
        print(f"[regenerate] ERROR: outputs dir does not exist: {outputs_dir}")
        sys.exit(1)

    reports = _collect_metric_reports(outputs_dir)

    if args.metrics:
        requested = {m.strip() for m in args.metrics.split(",")}
        reports = {k: v for k, v in reports.items() if k in requested}
        if not reports:
            print(
                f"[regenerate] ERROR: No reports found for requested metrics: {requested}"
            )
            sys.exit(1)
        print(f"[regenerate] Filtered to {len(reports)} metric(s): {', '.join(reports.keys())}")

    if not reports and not args.from_cache:
        print("[regenerate] No metric_*.md reports found. Nothing to do.")
        sys.exit(0)
    if not reports and args.from_cache:
        print("[regenerate] No metric_*.md reports found — proceeding from cache only (reports_md will be empty).")

    week_ending = args.week_ending or (reports and _infer_week_ending(reports)) or "unknown"
    print(f"[regenerate] Week ending: {week_ending}")
    if reports:
        print(f"[regenerate] Reports: {', '.join(reports.keys())}")

    cache = None if args.no_cache or args.cache_only else _load_cache(outputs_dir)
    use_cache = cache is not None and (args.from_cache or not args.no_cache) and not args.cache_only
    if args.from_cache and not cache:
        print("[regenerate] ERROR: --from-cache but executive_brief_input_cache.json not found")
        sys.exit(1)

    if use_cache:
        digest = cache["digest"]
        week_ending = cache.get("period_end", week_ending)
        metric_count = cache.get("metric_count", len(reports))
        print(f"[regenerate] Using digest from cache (period_end={week_ending})")
    else:
        digest = _build_digest(reports)
        if args.use_json:
            from data_analyst_agent.sub_agents.executive_brief_agent.agent import (
                _collect_metric_json_data as _cjd,
                _build_digest_from_json as _bdfj,
            )
            json_data = _cjd(outputs_dir)
            if args.metrics:
                requested = {m.strip() for m in args.metrics.split(",")}
                json_data = {k: v for k, v in json_data.items() if k in requested}
            if json_data:
                digest = _bdfj(json_data, reports, max_cards=6)
                print(f"[regenerate] Using JSON-backed digest ({len(json_data)} metrics)")
            else:
                print("[regenerate] No JSON files found, using markdown digest")
        else:
            print("[regenerate] Using markdown-only digest")
        metric_count = len(reports)

    print(f"[regenerate] Digest size: {len(digest)} chars")

    if args.digest_only:
        print("\n" + "=" * 80)
        print("DIGEST (--digest-only)")
        print("=" * 80)
        print(digest)
        print("=" * 80)
        sys.exit(0)

    from data_analyst_agent.sub_agents.executive_brief_agent.prompt import (
        EXECUTIVE_BRIEF_INSTRUCTION,
        SCOPED_BRIEF_PREAMBLE,
        load_dataset_specific_append,
        load_prompt_variant,
    )
    from data_analyst_agent.sub_agents.executive_brief_agent.agent import (
        _format_analysis_period,
        _collect_metric_json_data,
        _build_digest_from_json,
        _discover_level_entities,
        _load_hierarchy_level_mapping,
        _build_scoped_digest,
        _sanitize_entity_name,
    )
    from config.model_loader import get_agent_model, get_agent_thinking_config
    from google.genai import Client, types

    contract = None
    try:
        from config.dataset_resolver import get_dataset_path
        from data_analyst_agent.semantic.models import DatasetContract
        contract_path = get_dataset_path("contract.yaml")
        contract = DatasetContract.from_yaml(str(contract_path))
    except Exception:
        pass
    analysis_period = cache.get("analysis_period", _format_analysis_period(week_ending, contract)) if use_cache and cache else _format_analysis_period(week_ending, contract)

    if args.cache_only:
        weather_block = ""
        if os.environ.get("WEATHER_CONTEXT_ENABLED", "false").lower() == "true":
            weather_block = _run_weather_context_agent(outputs_dir)
            if weather_block:
                print(f"[regenerate] Weather context enabled: {len(weather_block)} chars appended")
        full_digest = digest + "\n\n" + weather_block if weather_block else digest
        _write_cache(
            outputs_dir,
            full_digest,
            week_ending,
            analysis_period,
            list(reports.keys()),
            {},
            None,
            "unknown",
        )
        print("[regenerate] Cache written (--cache-only). Exiting.")
        sys.exit(0)

    instruction = EXECUTIVE_BRIEF_INSTRUCTION.format(
        metric_count=metric_count,
        analysis_period=analysis_period,
        scope_preamble="",
        dataset_specific_append=load_dataset_specific_append(),
        prompt_variant_append=load_prompt_variant(args.prompt_variant),
    )

    weather_block = ""
    if not use_cache and os.environ.get("WEATHER_CONTEXT_ENABLED", "false").lower() == "true":
        weather_block = _run_weather_context_agent(outputs_dir)
        if weather_block:
            print(f"[regenerate] Weather context enabled: {len(weather_block)} chars appended")

    if use_cache:
        user_message = (
            f"Here are the individual metric analysis summaries for {analysis_period}.\n\n"
            f"{digest}\n\n"
            "Generate the executive brief JSON as instructed."
        )
    else:
        user_message = (
            f"Here are the individual metric analysis summaries for {analysis_period}.\n\n"
            f"{digest}\n\n"
            f"{weather_block}"
            "Generate the executive brief JSON as instructed."
        )

    model_name = args.model or get_agent_model("executive_brief_agent")
    if args.model:
        print(f"[regenerate] Model override: {args.model}")
    thinking_config = get_agent_thinking_config("executive_brief_agent")

    config_kwargs = {
        "response_modalities": ["TEXT"],
        "temperature": 0.05,
    }
    if thinking_config is not None:
        config_kwargs["thinking_config"] = thinking_config

    gen_cfg = types.GenerateContentConfig(
        system_instruction=instruction,
        **config_kwargs,
    )

    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    project = os.getenv("GOOGLE_CLOUD_PROJECT") if use_vertex else None

    print(f"[regenerate] Calling LLM (model={model_name})...")
    client = Client(
        vertexai=use_vertex,
        project=project,
        location=location if use_vertex else None,
    )

    raw = None
    last_err = None
    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_message,
                config=gen_cfg,
            )
            raw = (response.text or "").strip()
            break
        except Exception as e:
            last_err = e
            print(f"[regenerate] Attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                print("[regenerate] Retrying in 5s...")
                time.sleep(5)

    if raw is None:
        print(f"[regenerate] ERROR: All attempts failed. Last: {last_err}")
        sys.exit(1)

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        brief_data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[regenerate] ERROR: JSON parse failed. Raw response (first 500 chars):\n{raw[:500]}")
        sys.exit(1)

    brief_md = _format_brief(brief_data)

    brief_filename = f"executive_brief_{week_ending}.md"
    brief_path = outputs_dir / brief_filename
    brief_path.write_text(brief_md, encoding="utf-8")

    print(f"[regenerate] Saved executive brief to {brief_path}")
    print(f"[regenerate] File size: {brief_path.stat().st_size} bytes")
    print("\n" + "=" * 80)
    print("EXECUTIVE BRIEF")
    print("=" * 80)
    print(brief_md)
    print("=" * 80)

    # Accumulate BriefPage objects for PDF rendering (Spec 033)
    from data_analyst_agent.sub_agents.executive_brief_agent.pdf_renderer import (
        BriefPage,
        render_briefs_to_pdf,
    )
    brief_pages: list[BriefPage] = [
        BriefPage(
            bookmark_label=f"Network \u2014 {week_ending}",
            markdown_content=brief_md,
            level=0,
        )
    ]

    # --- Spec 032: Scoped brief generation loop ---
    if drill_levels >= 1:
        # Load or build JSON data for scoped digest construction
        regen_json_data: dict = {}
        if not use_cache or drill_levels >= 1:
            regen_json_data = _collect_metric_json_data(outputs_dir)
            if args.metrics:
                requested_metrics = {m.strip() for m in args.metrics.split(",")}
                regen_json_data = {k: v for k, v in regen_json_data.items() if k in requested_metrics}

        # Pre-load scoped digests from v2 cache
        cached_scoped: dict[str, str] = {}
        if use_cache and cache and cache.get("version", 1) >= 2:
            cached_scoped = cache.get("scoped_digests") or {}
            if cached_scoped:
                print(f"[regenerate] Loaded {len(cached_scoped)} scoped digest(s) from cache")

        # When no metric JSON files exist but cached digests are available,
        # use the cached entities/digests directly (supports --from-cache without metric files)
        if not regen_json_data and not cached_scoped:
            print("[regenerate] No metric_*.json found and no cached scoped digests — cannot generate scoped briefs. Skipping.")
        else:
            print(f"\n[regenerate] Drill levels={drill_levels}: generating scoped briefs")
            _scope_level_labels = {1: "Region", 2: "Terminal"}
            scoped_digests_map: dict[str, str] = {}

            # Determine which entities to process at each level.
            # When JSON data is unavailable, fall back to cached_scoped keys (one level assumed).
            def _get_level_entities(level: int) -> list[str]:
                if regen_json_data:
                    ents = _discover_level_entities(regen_json_data, level)
                    return ents[:max_scope_entities] if level == 2 else ents
                if level == 1 and cached_scoped:
                    return sorted(cached_scoped.keys())
                return []

            for level in range(1, min(drill_levels, 2) + 1):
                entities = _get_level_entities(level)
                level_name = _scope_level_labels.get(level, f"Level {level}")
                print(f"[regenerate] Level {level} ({level_name}): {len(entities)} entities: {', '.join(entities)}")

                # Load definitive parent→children mapping once for this level
                hierarchy_map = _load_hierarchy_level_mapping(regen_json_data, level, level + 1) if regen_json_data else {}
                if hierarchy_map:
                    print(f"[regenerate] Hierarchy mapping loaded ({sum(len(v) for v in hierarchy_map.values())} children across {len(hierarchy_map)} parents)")
                elif regen_json_data:
                    print(f"[regenerate] No hierarchy mapping found — using Strategy A (LLM-scoped) fallback")

                for entity in entities:
                    scope_children = set(hierarchy_map.get(entity, [])) if hierarchy_map else None
                    # Use cached scoped digest if available, else rebuild
                    if entity in cached_scoped:
                        scoped_digest = cached_scoped[entity]
                        print(f"[regenerate] Using cached scoped digest for {entity}")
                    else:
                        scoped_digest = _build_scoped_digest(
                            regen_json_data, reports, entity, level, analysis_period,
                            scope_children=scope_children,
                        )
                    scoped_digests_map[entity] = scoped_digest

                    scope_preamble = SCOPED_BRIEF_PREAMBLE.format(
                        scope_entity=entity,
                        scope_level_name=level_name.lower(),
                    )
                    scoped_instruction = EXECUTIVE_BRIEF_INSTRUCTION.format(
                        metric_count=metric_count,
                        analysis_period=analysis_period,
                        scope_preamble=scope_preamble,
                        dataset_specific_append=load_dataset_specific_append(),
                        prompt_variant_append=load_prompt_variant(args.prompt_variant),
                    )
                    scoped_user_message = (
                        f"Here are the individual metric analysis summaries for {analysis_period}, "
                        f"scoped to the {entity} {level_name.lower()}.\n\n"
                        f"{scoped_digest}\n\n"
                        "Generate the executive brief JSON as instructed. "
                        f"Focus exclusively on the {entity} {level_name.lower()} scope."
                    )

                    scoped_gen_cfg = types.GenerateContentConfig(
                        system_instruction=scoped_instruction,
                        response_modalities=["TEXT"],
                        temperature=0.05,
                        **({"thinking_config": thinking_config} if thinking_config is not None else {}),
                    )

                    print(f"[regenerate] Calling LLM for scoped brief: {entity} ({level_name})...")
                    scoped_raw: str | None = None
                    scoped_last_err = None
                    for attempt in range(1, 4):
                        try:
                            scoped_resp = client.models.generate_content(
                                model=model_name,
                                contents=scoped_user_message,
                                config=scoped_gen_cfg,
                            )
                            scoped_raw = (scoped_resp.text or "").strip()
                            break
                        except Exception as scope_e:
                            scoped_last_err = scope_e
                            print(f"[regenerate] Scoped attempt {attempt}/3 failed for {entity}: {scope_e}")
                            if attempt < 3:
                                print("[regenerate] Retrying in 5s...")
                                time.sleep(5)

                    if scoped_raw is None:
                        print(f"[regenerate] ERROR: All attempts failed for {entity}. Skipping.")
                        continue

                    scoped_raw = re.sub(r"^```(?:json)?\s*", "", scoped_raw)
                    scoped_raw = re.sub(r"\s*```$", "", scoped_raw)
                    try:
                        scoped_brief_data = json.loads(scoped_raw)
                    except json.JSONDecodeError:
                        print(f"[regenerate] ERROR: JSON parse failed for scoped brief {entity}. Skipping.")
                        continue

                    scoped_brief_md = _format_brief(scoped_brief_data)
                    safe_entity = _sanitize_entity_name(entity)
                    scoped_filename = f"executive_brief_{week_ending}_{safe_entity}.md"
                    scoped_path = outputs_dir / scoped_filename
                    scoped_path.write_text(scoped_brief_md, encoding="utf-8")
                    print(f"[regenerate] Saved scoped brief for {entity} to {scoped_path}")
                    brief_pages.append(
                        BriefPage(
                            bookmark_label=f"{entity} ({level_name})",
                            markdown_content=scoped_brief_md,
                            level=level,
                        )
                    )

            # Update cache to v2 with scoped digests
            if scoped_digests_map:
                _write_cache(
                    outputs_dir,
                    (digest + "\n\n" + weather_block) if weather_block else digest,
                    week_ending,
                    analysis_period,
                    list(reports.keys()),
                    {},
                    None,
                    "unknown",
                    drill_levels=drill_levels,
                    scoped_digests=scoped_digests_map,
                )

    # --- Spec 033: PDF Export ---
    if output_format in ("pdf", "both") and brief_pages:
        pdf_out = outputs_dir / f"executive_brief_{week_ending}.pdf"
        render_briefs_to_pdf(brief_pages, pdf_out, period_label=week_ending)


if __name__ == "__main__":
    main()
