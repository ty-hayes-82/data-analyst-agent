import json
from types import SimpleNamespace

import pytest

from data_analyst_agent.sub_agents.executive_brief_agent import agent as executive_agent


class _DummyResponse:
    def __init__(self, text: str):
        self.text = text


class _DummyModels:
    def __init__(self, text: str):
        self._text = text

    def generate_content(self, *, model: str, contents, config=None):
        return _DummyResponse(self._text)


class _DummyClient:
    def __init__(self, text: str):
        self.models = _DummyModels(text)


def test_report_error_reason_strict_patterns() -> None:
    assert executive_agent._report_error_reason("# Error Generating Report\n\nError: boom") == "report_generation_error"  # type: ignore[attr-defined]
    assert executive_agent._report_error_reason("") == "empty_report"  # type: ignore[attr-defined]
    assert executive_agent._report_error_reason("short") == "too_short"  # type: ignore[attr-defined]


def test_report_error_reason_allows_valid_content_with_error_word() -> None:
    markdown = (
        "# Revenue Report - West\n\n"
        "## Executive Summary\n"
        "Error rates declined 12% while revenue increased by $420K versus prior week. "
        "Variance drivers include Fuel (+$210K) and Linehaul (+$155K)."
    )
    assert executive_agent._report_error_reason(markdown) is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_llm_generate_brief_raises_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executive_agent.genai, "Client", lambda: _DummyClient(text="{not-json}"))

    with pytest.raises(RuntimeError, match="invalid JSON from LLM"):
        await executive_agent._llm_generate_brief(  # type: ignore[attr-defined]
            model_name="test-model",
            instruction="write",
            user_message="hello",
            thinking_config=None,
            digest="- West variance improved\n- South variance improved",
            section_contract=None,
        )


@pytest.mark.asyncio
async def test_llm_generate_brief_parses_json_with_preamble(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "header": {
            "title": "2024-03-10 – Demand up $2.4M (+2.1%) from Southwest growth",
            "summary": "Overall demand increased $2.4M (+2.1%) to $115M compared to the prior week baseline of $112.6M, driven primarily by Southwest region growth ($4.2M increase, 175% of total variance). Northeast region remained flat at $65M due to customs processing delays.",
        },
        "body": {
            "sections": [
                {
                    "title": "Executive Summary",
                    "content": "Network operations stabilized after prior-week volatility with modest growth driven by Southwest region.",
                    "insights": [],
                },
                {
                    "title": "Key Findings",
                    "content": "Southwest drove the rebound while Northeast lagged due to operational constraints.",
                    "insights": [
                        {
                            "title": "Southwest e-commerce drove growth",
                            "details": "Southwest region increased $4.2M (+4.2%) compared to the prior week baseline of $100M, driven by Arizona electronics orders accounting for $2.8M (67% of regional variance). This represents the strongest regional performance.",
                        },
                        {
                            "title": "Midwest auto sector declined",
                            "details": "Midwest region declined $1.8M (-2.1%) compared to the prior week baseline of $85M, primarily from Michigan automotive suppliers which dropped $1.5M (83% of regional decline). This appears temporary after strong +8.5% prior-period performance.",
                        },
                        {
                            "title": "Northeast customs delays persist",
                            "details": "Northeast region remained flat at $65M (0.3% variance) compared to the prior week, as New York customs backlog cleared $18M in delayed shipments. Transaction counts averaged 2,450 daily vs normal 2,500, suggesting 2% processing drag.",
                        },
                    ],
                },
                {
                    "title": "Forward Outlook",
                    "content": "Focus on resolving NY customs backlog while sustaining Southwest momentum. Monitor Midwest for rebound signals in the coming weeks.",
                    "insights": [],
                },
            ]
        },
    }
    response_text = "Sure, synthesizing the brief now.\n" + json.dumps(payload) + "\nHope this helps!"
    monkeypatch.setattr(executive_agent.genai, "Client", lambda: _DummyClient(text=response_text))

    brief_json, brief_md, used_fallback = await executive_agent._llm_generate_brief(  # type: ignore[attr-defined]
        model_name="test-model",
        instruction="write",
        user_message="hello",
        thinking_config=None,
        digest="- Sample metric signal",
        section_contract=executive_agent.NETWORK_SECTION_CONTRACT,
    )

    assert used_fallback is False
    assert brief_json["header"]["title"] == payload["header"]["title"]
    sections = brief_json["body"].get("sections") or []
    assert len(sections) == len(payload["body"]["sections"])
    assert "Key Findings" in brief_md


@pytest.mark.asyncio
async def test_executive_brief_partial_digest_quality_continues_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    reports = {
        "good_metric": (
            "# Good Metric\n\n"
            "## Executive Summary\n"
            "Revenue increased by $420K (+3.2%) versus prior week with stable quality checks."
        ),
        "broken_metric": "# Error Generating Report\n\nError: boom",
    }
    brief_payload = {
        "header": {"title": "Executive Brief", "summary": "Revenue +$420K (+3.2%) vs prior week."},
        "body": {
            "sections": [
                {"title": "Executive Summary", "content": "Network stable at $12.4M (+1.2%).", "insights": []},
                {
                    "title": "Key Findings",
                    "content": "Mixed signal by region.",
                    "insights": [
                        {"title": "West", "details": "West increased $220K (+2.1%) vs prior week baseline $10.5M."},
                        {"title": "East", "details": "East decreased $80K (-1.4%) vs prior week baseline $5.7M."},
                        {"title": "Central", "details": "Central increased $140K (+3.9%) with 2.2 z-score signal."},
                    ],
                },
                {"title": "Forward Outlook", "content": "Monitor next week for continuity.", "insights": []},
            ]
        },
    }

    async def _fake_llm_generate_brief(**kwargs):
        return brief_payload, "# Brief\n\nHealthy partial digest output.", False

    monkeypatch.setenv("DATA_ANALYST_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("EXECUTIVE_BRIEF_OUTPUT_FORMAT", "none")
    monkeypatch.delenv("SKIP_EXECUTIVE_BRIEF_LLM", raising=False)
    monkeypatch.setattr(executive_agent, "_collect_metric_reports", lambda _out: reports)
    monkeypatch.setattr(executive_agent, "_collect_metric_json_data", lambda _out: {})
    monkeypatch.setattr(executive_agent, "_build_digest", lambda _reports: "digest")
    monkeypatch.setattr(executive_agent, "_write_executive_brief_cache", lambda **kwargs: None)
    monkeypatch.setattr(executive_agent, "_llm_generate_brief", _fake_llm_generate_brief)
    monkeypatch.setattr(executive_agent, "get_agent_model", lambda _name: "test-model")
    monkeypatch.setattr(executive_agent, "get_agent_thinking_config", lambda _name: None)

    session = SimpleNamespace(
        state={
            "timeframe": {"end": "2026-03-14"},
            "analysis_period": "the week ending 2026-03-14",
            "dataset": "ops_metrics_ds",
            "dataset_contract": None,
        },
        events=[],
    )
    ctx = SimpleNamespace(invocation_id="unit-test", session=session)
    agent = executive_agent.CrossMetricExecutiveBriefAgent()
    events = [event async for event in agent._run_async_impl(ctx)]

    captured = capsys.readouterr().out
    assert "Proceeding with partial digest quality: 1/2 metric reports usable." in captured
    assert "[BRIEF] All metric reports are unusable. Skipping LLM call." not in captured
    assert events
    assert (tmp_path / "deliverables" / "brief.md").exists()
