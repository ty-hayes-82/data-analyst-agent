import pytest
pytestmark = pytest.mark.skip(reason="requires /data/remote_a2a/ which is not present")

# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for Hyper connection recovery logic (T067).

These tests verify that _try_reconnect() correctly handles stale/broken
connections without requiring a real tableauhyperapi installation.

We load the hyper_manager file directly via spec_from_file_location to avoid
triggering the agent package __init__.py (which imports the full ADK app).
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

_WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent  # c:\GITLAB


def _make_stubs() -> dict:
    """Return sys.modules stubs needed to import hyper_manager in isolation."""
    mock_hyper = MagicMock()
    mock_hyper.HyperProcess = MagicMock
    mock_hyper.Connection = MagicMock
    mock_hyper.Telemetry = MagicMock()

    mock_tdsx = MagicMock()
    mock_hyper_io = MagicMock()

    mock_tableau_shared = types.ModuleType("remote_a2a.utils.tableau_shared")
    mock_tableau_shared.tdsx = mock_tdsx
    mock_tableau_shared.hyper_io = mock_hyper_io

    mock_remote_a2a = types.ModuleType("remote_a2a")
    mock_utils = types.ModuleType("remote_a2a.utils")

    return {
        "tableauhyperapi": mock_hyper,
        "remote_a2a": mock_remote_a2a,
        "remote_a2a.utils": mock_utils,
        "remote_a2a.utils.tableau_shared": mock_tableau_shared,
        "remote_a2a.utils.tableau_shared.tdsx": mock_tdsx,
        "remote_a2a.utils.tableau_shared.hyper_io": mock_hyper_io,
        "yaml": MagicMock(),
    }


def _load_hyper_manager_from_file() -> types.ModuleType:
    """Load hyper_manager.py directly (bypassing the package __init__.py chain)."""
    hm_path = (
        _WORKSPACE_ROOT
        / "remote_a2a"
        / "tableau_ops_metrics_ds_agent"
        / "shared_libraries"
        / "hyper_manager.py"
    )
    spec = importlib.util.spec_from_file_location("_hm_test_isolated", hm_path)
    mod = importlib.util.module_from_spec(spec)
    stubs = _make_stubs()
    with patch.dict("sys.modules", stubs):
        spec.loader.exec_module(mod)
    return mod


# Cache the loaded module for the test session so we don't reload it every test
_HM = None


def _get_hm():
    global _HM
    if _HM is None:
        _HM = _load_hyper_manager_from_file()
    return _HM


class TestConnectionRecovery:
    """T067: _try_reconnect() behaviour under various failure scenarios."""

    @staticmethod
    def _reset(mod):
        """Reset module-level globals to an un-initialized state."""
        mod._CONNECTION_INITIALIZED = False
        mod._HYPER_PROCESS = None
        mod._HYPER_CONNECTION = None
        mod._HYPER_PATH = "/fake/path/test.hyper"

    def test_reconnect_succeeds_on_first_attempt(self):
        """_try_reconnect should return True when initialize_persistent_connection works."""
        mod = _get_hm()
        self._reset(mod)

        def fake_init():
            mod._CONNECTION_INITIALIZED = True
            mod._HYPER_CONNECTION = MagicMock()

        with patch.object(mod, "initialize_persistent_connection", side_effect=fake_init):
            with patch.object(mod, "cleanup_persistent_connection"):
                result = mod._try_reconnect(max_attempts=3, backoff_s=0.0)

        assert result is True
        assert mod._CONNECTION_INITIALIZED is True

    def test_reconnect_retries_on_failure_then_succeeds(self):
        """_try_reconnect should retry and succeed on the second attempt."""
        mod = _get_hm()
        self._reset(mod)
        call_count = {"n": 0}

        def fake_init():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise RuntimeError("simulated startup failure")
            mod._CONNECTION_INITIALIZED = True
            mod._HYPER_CONNECTION = MagicMock()

        with patch.object(mod, "initialize_persistent_connection", side_effect=fake_init):
            with patch.object(mod, "cleanup_persistent_connection"):
                result = mod._try_reconnect(max_attempts=3, backoff_s=0.0)

        assert result is True
        assert call_count["n"] == 2

    def test_reconnect_fails_after_max_attempts(self):
        """_try_reconnect should return False after all retry attempts are exhausted."""
        mod = _get_hm()
        self._reset(mod)

        def always_fail():
            raise RuntimeError("permanent failure")

        with patch.object(mod, "initialize_persistent_connection", side_effect=always_fail):
            with patch.object(mod, "cleanup_persistent_connection"):
                result = mod._try_reconnect(max_attempts=3, backoff_s=0.0)

        assert result is False
        assert mod._CONNECTION_INITIALIZED is False

    def test_get_persistent_connection_triggers_recovery_on_stale(self):
        """get_persistent_connection() detects stale connection and calls _try_reconnect."""
        mod = _get_hm()

        mock_conn = MagicMock()
        mock_conn.execute_query.side_effect = RuntimeError("connection lost")

        mod._CONNECTION_INITIALIZED = True
        mod._HYPER_CONNECTION = mock_conn
        mod._HYPER_PATH = "/fake/path/test.hyper"

        recovered_conn = MagicMock()

        def fake_reconnect(**kwargs):
            mod._CONNECTION_INITIALIZED = True
            mod._HYPER_CONNECTION = recovered_conn
            return True

        with patch.object(mod, "_try_reconnect", side_effect=fake_reconnect) as mock_reconnect:
            result_conn = mod.get_persistent_connection()

        mock_reconnect.assert_called_once()
        assert result_conn is recovered_conn

    def test_get_persistent_connection_returns_none_if_recovery_fails(self):
        """get_persistent_connection() returns None when recovery ultimately fails."""
        mod = _get_hm()

        mock_conn = MagicMock()
        mock_conn.execute_query.side_effect = RuntimeError("connection lost")

        mod._CONNECTION_INITIALIZED = True
        mod._HYPER_CONNECTION = mock_conn
        mod._HYPER_PATH = "/fake/path/test.hyper"

        def failed_reconnect(**kwargs):
            mod._CONNECTION_INITIALIZED = False
            mod._HYPER_CONNECTION = None
            return False

        with patch.object(mod, "_try_reconnect", side_effect=failed_reconnect):
            result_conn = mod.get_persistent_connection()

        assert result_conn is None

    def test_is_ready_false_when_not_initialized(self):
        """is_ready() returns False when _CONNECTION_INITIALIZED is False."""
        mod = _get_hm()
        mod._CONNECTION_INITIALIZED = False
        mod._HYPER_CONNECTION = None
        mod._HYPER_PATH = None
        mod._AGGREGATION_CONFIG.clear()
        assert mod.is_ready() is False

    def test_is_ready_true_when_fully_initialized(self, tmp_path):
        """is_ready() returns True when all conditions are met."""
        mod = _get_hm()
        fake_hyper = tmp_path / "test.hyper"
        fake_hyper.write_bytes(b"")
        mod._HYPER_PATH = str(fake_hyper)
        mod._CONNECTION_INITIALIZED = True
        mod._HYPER_CONNECTION = MagicMock()
        mod._AGGREGATION_CONFIG.update({"period_type": "month_end"})
        assert mod.is_ready() is True
        mod._AGGREGATION_CONFIG.clear()
