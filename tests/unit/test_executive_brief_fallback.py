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
    assert "Executive Brief" in brief_md
    assert "Fallback" in brief_json["header"]["title"]
    assert brief_json["body"]["sections"], "Fallback JSON should include sections"
