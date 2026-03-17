"""
Unit tests for HyperConnectionManager — mocked Hyper API tests for connection lifecycle.
"""

import os
import pytest
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import (
    HyperLoaderConfig,
    HyperConfig,
)
from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import (
    HyperConnectionManager,
    get_or_create_manager,
    _MANAGERS,
)


@pytest.fixture(autouse=True)
def clear_manager_registry():
    """Ensure each test starts with a clean manager registry."""
    _MANAGERS.clear()
    yield
    _MANAGERS.clear()


@pytest.fixture
def basic_config():
    return HyperLoaderConfig(
        hyper=HyperConfig(
            tdsx_file="Test.tdsx",
            tdsx_path="data/test",
            default_table="Extract.Extract",
            extract_dir="temp_extracted/test",
        ),
    )


# ---------------------------------------------------------------------------
# Tests — Manager registry
# ---------------------------------------------------------------------------

class TestManagerRegistry:
    def test_get_or_create_returns_same_instance(self, basic_config):
        m1 = get_or_create_manager("test_ds", basic_config)
        m2 = get_or_create_manager("test_ds", basic_config)
        assert m1 is m2

    def test_different_keys_return_different_instances(self, basic_config):
        m1 = get_or_create_manager("ds_a", basic_config)
        m2 = get_or_create_manager("ds_b", basic_config)
        assert m1 is not m2


# ---------------------------------------------------------------------------
# Tests — TDSX extraction
# ---------------------------------------------------------------------------

class TestTDSXExtraction:
    def test_extract_from_tdsx_creates_hyper_file(self, tmp_path):
        """Create a minimal .tdsx (ZIP) with a .hyper file inside and extract it."""
        # Create a fake .hyper file
        hyper_content = b"fake hyper data"
        tdsx_path = tmp_path / "Test.tdsx"
        with zipfile.ZipFile(str(tdsx_path), "w") as zf:
            zf.writestr("Data/Extracts/Test.hyper", hyper_content)

        extract_dir = tmp_path / "extracted"
        result = HyperConnectionManager._extract_hyper_from_tdsx(
            str(tdsx_path), str(extract_dir)
        )
        assert result.endswith(".hyper")
        assert os.path.exists(result)

    def test_extract_from_tdsx_no_hyper_raises(self, tmp_path):
        """TDSX without a .hyper file should raise ValueError."""
        tdsx_path = tmp_path / "Empty.tdsx"
        with zipfile.ZipFile(str(tdsx_path), "w") as zf:
            zf.writestr("metadata.xml", "<xml/>")

        extract_dir = tmp_path / "extracted"
        with pytest.raises(ValueError, match="No .hyper file"):
            HyperConnectionManager._extract_hyper_from_tdsx(
                str(tdsx_path), str(extract_dir)
            )


# ---------------------------------------------------------------------------
# Tests — Connection state
# ---------------------------------------------------------------------------

class TestConnectionState:
    def test_is_ready_false_before_init(self, basic_config):
        mgr = HyperConnectionManager("test", basic_config)
        assert mgr.is_ready() is False

    def test_get_hyper_path_none_before_extract(self, basic_config):
        mgr = HyperConnectionManager("test", basic_config)
        assert mgr.get_hyper_path() is None

    def test_get_default_table(self, basic_config):
        mgr = HyperConnectionManager("test", basic_config)
        assert mgr.get_default_table() == "Extract.Extract"

    def test_cleanup_safe_when_not_initialized(self, basic_config):
        mgr = HyperConnectionManager("test", basic_config)
        # Should not raise even with no active connection
        mgr.cleanup()
        assert mgr.is_ready() is False


# ---------------------------------------------------------------------------
# Tests — ensure_extracted with real filesystem
# ---------------------------------------------------------------------------

class TestEnsureExtracted:
    @patch("data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection.HYPER_API_AVAILABLE", False)
    def test_ensure_extracted_raises_if_no_hyper_api(self, basic_config):
        mgr = HyperConnectionManager("test", basic_config)
        with pytest.raises(ImportError, match="tableauhyperapi"):
            mgr.ensure_extracted(Path("/fake/root"))

    def test_ensure_extracted_reuses_cached_hyper(self, tmp_path, basic_config):
        """If a .hyper already exists in extract_dir and is fresh, reuse it."""
        mgr = HyperConnectionManager("test", basic_config)

        # Create fake tdsx
        tdsx_dir = tmp_path / "data" / "test"
        tdsx_dir.mkdir(parents=True)
        tdsx_path = tdsx_dir / "Test.tdsx"
        with zipfile.ZipFile(str(tdsx_path), "w") as zf:
            zf.writestr("Data/Extracts/Test.hyper", b"fake")

        # Pre-populate extract dir with a "cached" hyper
        extract_dir = tmp_path / "temp_extracted" / "test"
        extract_dir.mkdir(parents=True)
        cached_hyper = extract_dir / "Test.hyper"
        cached_hyper.write_bytes(b"cached fake")
        # Make the cached file newer than the TDSX
        os.utime(str(cached_hyper), (9999999999, 9999999999))

        result = mgr.ensure_extracted(tmp_path)
        assert result == str(cached_hyper)
