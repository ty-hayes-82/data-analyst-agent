import json

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


@pytest.mark.asyncio
async def test_llm_generate_brief_falls_back_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executive_agent.genai, "Client", lambda: _DummyClient(text="{not-json}"))

    brief_json, brief_md, used_fallback = await executive_agent._llm_generate_brief(  # type: ignore[attr-defined]
        model_name="test-model",
        instruction="write",
        user_message="hello",
        thinking_config=None,
        digest="- West variance improved\n- South variance improved",
        section_contract=None,
    )

    assert used_fallback is True
    assert "Data Monitoring Summary" in brief_md
    assert "Data Monitoring Summary" in brief_json["header"]["title"]
    assert brief_json["body"]["sections"], "Fallback JSON should include sections"


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
                    "title": "Recommended Actions",
                    "content": "Focus on resolving NY customs backlog while sustaining Southwest momentum. Monitor Midwest for rebound signals.",
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
