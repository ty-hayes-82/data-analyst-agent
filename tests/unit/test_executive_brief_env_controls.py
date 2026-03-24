from data_analyst_agent.sub_agents.executive_brief_agent import agent as executive_agent


def test_max_scoped_briefs_default(monkeypatch):
    monkeypatch.delenv("EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS", raising=False)
    assert executive_agent._max_scoped_briefs() == 20


def test_max_scoped_briefs_env_override(monkeypatch):
    monkeypatch.setenv("EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS", "5")
    assert executive_agent._max_scoped_briefs() == 5


def test_scope_concurrency_default(monkeypatch):
    monkeypatch.delenv("EXECUTIVE_BRIEF_SCOPE_CONCURRENCY", raising=False)
    assert executive_agent._scope_concurrency_limit() == 3


def test_scope_concurrency_invalid_values_fall_back(monkeypatch):
    monkeypatch.setenv("EXECUTIVE_BRIEF_SCOPE_CONCURRENCY", "-2")
    assert executive_agent._scope_concurrency_limit() == 3


def test_scope_concurrency_env_override(monkeypatch):
    monkeypatch.setenv("EXECUTIVE_BRIEF_SCOPE_CONCURRENCY", "4")
    assert executive_agent._scope_concurrency_limit() == 4
