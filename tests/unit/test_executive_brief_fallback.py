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
            "title": "2024-03-10 – Demand up 2% from Southwest growth",
            "summary": "Overall demand increased 2.1% compared to the prior week, driven primarily by Southwest region growth and electronics mix shift. Northeast region showed flat performance due to customs processing delays.",
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
                            "details": "Southwest region increased 4.2% compared to the prior week, driven by Arizona electronics orders. This represents the strongest regional performance and accounts for the majority of network growth.",
                        },
                        {
                            "title": "Midwest auto sector declined",
                            "details": "Midwest region declined 2.1% compared to the prior week, primarily from Michigan automotive suppliers. This appears to be a temporary pullback after strong prior-period performance.",
                        },
                        {
                            "title": "Northeast customs delays persist",
                            "details": "Northeast region remained flat compared to the prior week as New York customs backlog continued to clear slowly. Transaction counts suggest underlying demand is normal but processing delays are masking growth.",
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
