"""
Unit tests for config.dataset_resolver (spec 012-hardcoded-dataset-selection).

Tests:
- get_active_dataset reads from agent_config.yaml
- ACTIVE_DATASET env var overrides the YAML config
- get_dataset_path resolves existing files correctly
- get_dataset_path raises FileNotFoundError for missing files
- ContractLoader loads the correct contract without needing contract_selection in state
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATASETS_DIR = CONFIG_DIR / "datasets"


def _dataset_exists(name: str) -> bool:
    candidates = [
        DATASETS_DIR / name,
        DATASETS_DIR / "csv" / name,
        DATASETS_DIR / "tableau" / name,
    ]
    return any(path.exists() for path in candidates)


OPS_DATASET_AVAILABLE = _dataset_exists("ops_metrics")
ACCOUNT_DATASET_AVAILABLE = _dataset_exists("account_research")
ORDER_DISPATCH_AVAILABLE = _dataset_exists("order_dispatch")


# ---------------------------------------------------------------------------
# T032: get_active_dataset reads from agent_config.yaml
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_active_dataset_reads_from_yaml():
    """get_active_dataset() should return the value from agent_config.yaml."""
    from config.dataset_resolver import get_active_dataset, clear_dataset_cache

    clear_dataset_cache()
    # Ensure env var is not set
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ACTIVE_DATASET", None)
        result = get_active_dataset()

    assert isinstance(result, str)
    assert len(result) > 0, "active_dataset should not be empty"
    # The default configured value is trade_data
    assert result == "trade_data", f"Expected 'trade_data', got '{result}'"
    clear_dataset_cache()


@pytest.mark.unit
def test_get_active_dataset_returns_string():
    """get_active_dataset() return value should be a non-empty string."""
    from config.dataset_resolver import get_active_dataset, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ACTIVE_DATASET", None)
        result = get_active_dataset()

    assert isinstance(result, str)
    assert result.strip() != ""
    clear_dataset_cache()


# ---------------------------------------------------------------------------
# T033: ACTIVE_DATASET env var overrides YAML config
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_active_dataset_env_var_overrides_yaml():
    """ACTIVE_DATASET env var should take precedence over agent_config.yaml."""
    from config.dataset_resolver import get_active_dataset, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {"ACTIVE_DATASET": "ops_metrics"}):
        result = get_active_dataset()

    assert result == "ops_metrics", f"Expected 'ops_metrics' from env var, got '{result}'"
    clear_dataset_cache()


@pytest.mark.unit
def test_active_dataset_env_var_trade_data():
    """ACTIVE_DATASET env var works for the trade_data dataset."""
    from config.dataset_resolver import get_active_dataset, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {"ACTIVE_DATASET": "trade_data"}):
        result = get_active_dataset()

    assert result == "trade_data"
    clear_dataset_cache()


# ---------------------------------------------------------------------------
# T034: get_dataset_path resolves paths; raises for missing files
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_dataset_path_resolves_existing_file():
    """get_dataset_path('contract.yaml') should return an existing Path."""
    from config.dataset_resolver import get_active_dataset, get_dataset_path, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ACTIVE_DATASET", None)
        path = get_dataset_path("contract.yaml")

    assert path.exists(), f"Expected contract.yaml to exist at {path}"
    assert path.is_file()
    assert path.suffix == ".yaml"
    clear_dataset_cache()


@pytest.mark.unit
def test_get_dataset_path_for_trade_data():
    """get_dataset_path works when ACTIVE_DATASET=trade_data."""
    from config.dataset_resolver import get_dataset_path, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {"ACTIVE_DATASET": "trade_data"}):
        path = get_dataset_path("contract.yaml")

    assert path.exists()
    assert "trade_data" in str(path)
    clear_dataset_cache()


@pytest.mark.unit
def test_get_dataset_path_raises_for_missing_file():
    """get_dataset_path should raise FileNotFoundError for a file that doesn't exist."""
    from config.dataset_resolver import get_dataset_path, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {"ACTIVE_DATASET": "trade_data"}):
        with pytest.raises(FileNotFoundError) as exc_info:
            get_dataset_path("nonexistent_file_xyz.yaml")

    error_msg = str(exc_info.value)
    assert "nonexistent_file_xyz.yaml" in error_msg, "Error should mention the filename"
    assert "trade_data" in error_msg, "Error should mention the dataset name"
    clear_dataset_cache()


@pytest.mark.unit
def test_get_dataset_path_optional_returns_none_for_missing():
    """get_dataset_path_optional should return None for missing files instead of raising."""
    from config.dataset_resolver import get_dataset_path_optional, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {"ACTIVE_DATASET": "trade_data"}):
        result = get_dataset_path_optional("definitely_not_a_real_file.yaml")

    assert result is None
    clear_dataset_cache()


@pytest.mark.unit
def test_get_dataset_path_optional_returns_path_when_exists():
    """get_dataset_path_optional should return the Path when the file exists."""
    from config.dataset_resolver import get_dataset_path_optional, clear_dataset_cache

    clear_dataset_cache()
    with patch.dict(os.environ, {"ACTIVE_DATASET": "trade_data"}):
        result = get_dataset_path_optional("contract.yaml")

    assert result is not None
    assert result.exists()
    clear_dataset_cache()


# ---------------------------------------------------------------------------
# T035: ContractLoader loads from config/datasets without contract_selection
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_contract_loader_loads_without_contract_selection():
    """
    ContractLoader should load the contract from config/datasets/<active>/contract.yaml
    without requiring 'contract_selection' in session state.
    """
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.agents.invocation_context import InvocationContext
    from data_analyst_agent.agent import ContractLoader

    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name="test_app", user_id="test_user")

    # Crucially: do NOT set contract_selection in state
    assert "contract_selection" not in session.state

    agent = ContractLoader()
    ctx = InvocationContext(
        session=session,
        agent=agent,
        invocation_id="test-contract-loader",
        session_service=session_service,
    )

    import os
    env_backup = os.environ.pop("ACTIVE_DATASET", None)
    try:
        async for _ in agent.run_async(ctx):
            pass
    finally:
        if env_backup is not None:
            os.environ["ACTIVE_DATASET"] = env_backup

    assert "dataset_contract" in session.state, "ContractLoader must set dataset_contract"
    assert session.state["active_dataset"] is not None
    contract = session.state["dataset_contract"]
    assert contract.name, "Loaded contract should have a name"
    assert len(contract.metrics) > 0, "Loaded contract should have metrics"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_contract_loader_respects_active_dataset_env_var():
    """
    ContractLoader should load the ops_metrics contract when ACTIVE_DATASET=ops_metrics.
    """
    if not OPS_DATASET_AVAILABLE:
        pytest.skip("ops_metrics dataset not available in this workspace")
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.agents.invocation_context import InvocationContext
    from data_analyst_agent.agent import ContractLoader
    from config.dataset_resolver import clear_dataset_cache

    clear_dataset_cache()
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name="test_app", user_id="test_user_ops")

    agent = ContractLoader()
    ctx = InvocationContext(
        session=session,
        agent=agent,
        invocation_id="test-contract-loader-ops",
        session_service=session_service,
    )

    with patch.dict(os.environ, {"ACTIVE_DATASET": "ops_metrics"}):
        clear_dataset_cache()
        async for _ in agent.run_async(ctx):
            pass

    clear_dataset_cache()
    assert "dataset_contract" in session.state
    assert session.state["active_dataset"] == "ops_metrics"
    contract = session.state["dataset_contract"]
    assert contract.name == "Ops Metrics"


# ---------------------------------------------------------------------------
# Dataset folder structure sanity checks
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_trade_dataset_contract_exists():
    """The trade_data dataset must provide contract and loader configs."""
    trade_dir = DATASETS_DIR / "csv" / "trade_data"
    contract = trade_dir / "contract.yaml"
    loader = trade_dir / "loader.yaml"
    assert contract.exists(), f"Missing trade_data contract: {contract}"
    assert loader.exists(), f"Missing trade_data loader: {loader}"

@pytest.mark.unit
def test_no_unused_dataset_dirs_remain():
    """Ensure no legacy dataset directories linger after cleanup."""
    csv_root = DATASETS_DIR / "csv"
    names = sorted([d.name for d in csv_root.iterdir() if d.is_dir()]) if csv_root.exists() else []
    # Core datasets that must exist
    required = {"trade_data"}
    # Known public datasets (may or may not be present)
    known = {"trade_data", "covid_us_counties", "covid_us_counties_v2", "owid_co2_emissions",
             "co2_global_regions", "worldbank_population", "worldbank_population_regions",
             "global_temperature", "toll_data", "validation_ops"}
    assert required.issubset(set(names)), f"Missing required datasets: {required - set(names)}"
    unknown = set(names) - known
    assert not unknown, f"Unknown dataset directories: {sorted(unknown)}"



@pytest.mark.unit
def test_agent_config_yaml_exists():
    """config/agent_config.yaml must exist and contain active_dataset."""
    import yaml
    config_path = CONFIG_DIR / "agent_config.yaml"
    assert config_path.exists(), "config/agent_config.yaml not found"

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    assert "active_dataset" in cfg, "agent_config.yaml must have 'active_dataset' key"
    assert cfg["active_dataset"], "active_dataset must not be empty"


@pytest.mark.unit
def test_active_dataset_folder_exists():
    """The folder named by active_dataset in agent_config.yaml must exist."""
    import yaml
    from config.dataset_resolver import clear_dataset_cache

    clear_dataset_cache()
    with open(CONFIG_DIR / "agent_config.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    active = cfg.get("active_dataset", "")
    candidate_dirs = [
        DATASETS_DIR / active,
        DATASETS_DIR / "csv" / active,
        DATASETS_DIR / "tableau" / active,
    ]
    assert any(d.is_dir() for d in candidate_dirs), (
        f"Dataset folder '{active}' not found in config/datasets/"
    )
    clear_dataset_cache()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
