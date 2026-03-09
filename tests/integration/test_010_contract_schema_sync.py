"""
test_010_contract_schema_sync.py

Guard test: verifies that the pl_analyst contracts and config stay in sync
with the actual Tableau Hyper file schema.

Specifically:
  - ops_metrics_contract.yaml references correct table name and only columns
    that physically exist in the Hyper file.
  - ops_metrics_ratios_config.yaml references the correct sql_table and only
    columns that physically exist.
  - Neither file references stale identifiers (Custom SQL Query, empty_trf_mi).
  - total_miles metric is present in the contract.

Spec: pl_analyst/specs/010-a2a-integration-cleanup

Design notes
------------
- Skips if tableauhyperapi is not installed.
- Skips if the Hyper file does not exist (CI without extract).
- Uses Hyper API best practices: context managers throughout.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

try:
    from tableauhyperapi import Connection, HyperProcess, HyperException, Telemetry
    HYPER_API_AVAILABLE = True
except ImportError:
    HYPER_API_AVAILABLE = False
    HyperException = Exception  # fallback so references don't fail at import

pytestmark = pytest.mark.skipif(
    not HYPER_API_AVAILABLE,
    reason="tableauhyperapi not installed",
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HYPER_PATH = Path(
    r"C:\GITLAB\remote_a2a\tableau_ops_metrics_ds_agent"
    r"\temp_extracted\Data\Extracts\Ops Metrics.hyper"
)
CONTRACT_PATH = Path(r"C:\GITLAB\pl_analyst\config\datasets\ops_metrics\contract.yaml")
RATIOS_CONFIG_PATH = Path(r"C:\GITLAB\pl_analyst\config\datasets\ops_metrics\ratios.yaml")

EXPECTED_TABLE = '"Extract"."Extract"'
STALE_TABLE = "Custom SQL Query"
STALE_COLUMN = "empty_trf_mi"


# ---------------------------------------------------------------------------
# Hyper helpers
# ---------------------------------------------------------------------------

def _get_hyper_columns(hyper_path: Path) -> dict[str, set[str]]:
    """Return {table_name: {column_name, ...}} for all tables in the Hyper file."""
    result: dict[str, set[str]] = {}
    with tempfile.TemporaryDirectory(prefix="hyper_sync_test_") as log_dir:
        with HyperProcess(
            telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
            parameters={"log_dir": log_dir},
        ) as hyper:
            with Connection(
                endpoint=hyper.endpoint,
                database=str(hyper_path),
            ) as conn:
                with conn.execute_query(
                    "SELECT schemaname, tablename FROM pg_tables"
                ) as tq:
                    tables = [
                        (row[0], row[1])
                        for row in tq
                    ]
                for schema, table in tables:
                    qualified = f'"{schema}"."{table}"'
                    with conn.execute_query(
                        f"SELECT * FROM {qualified} LIMIT 0"
                    ) as col_q:
                        cols = {c.name.unescaped for c in col_q.schema.columns}
                    result[qualified] = cols
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def hyper_columns() -> dict[str, set[str]]:
    if not HYPER_PATH.exists():
        pytest.skip(f"Hyper file not found: {HYPER_PATH}")
    try:
        return _get_hyper_columns(HYPER_PATH)
    except HyperException as exc:
        if "locked" in str(exc).lower():
            pytest.skip(
                f"Hyper file is locked by another process (test_009 session fixture). "
                f"Run this test module in isolation to verify schema sync. Error: {exc}"
            )
        raise


@pytest.fixture(scope="module")
def ops_contract() -> dict[str, Any]:
    with open(CONTRACT_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def ratios_config() -> dict[str, Any]:
    with open(RATIOS_CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Contract YAML tests
# ---------------------------------------------------------------------------

class TestContractYaml:
    """Verify ops_metrics_contract.yaml is aligned with the live Hyper schema."""

    def test_facts_table_name_correct(self, ops_contract: dict[str, Any]) -> None:
        """contract.data_source.tables.facts must point to the current table."""
        facts = ops_contract["data_source"]["tables"]["facts"]
        assert STALE_TABLE not in facts, (
            f"Contract still references stale table '{STALE_TABLE}'; "
            f"current table is {EXPECTED_TABLE!r}."
        )
        assert EXPECTED_TABLE in facts, (
            f"Expected contract facts table to contain {EXPECTED_TABLE!r}, got {facts!r}."
        )

    def test_no_units_table_reference(self, ops_contract: dict[str, Any]) -> None:
        """'Current Unit Info' table no longer exists; contract must not list it."""
        tables = ops_contract["data_source"]["tables"]
        assert "units" not in tables, (
            "Contract still references the removed 'Current Unit Info' table under "
            "data_source.tables.units."
        )

    def test_no_stale_empty_trf_mi_column(self, ops_contract: dict[str, Any]) -> None:
        """No metric in the contract may reference the non-existent empty_trf_mi column."""
        for metric in ops_contract.get("metrics", []):
            col = metric.get("column", "")
            assert col != STALE_COLUMN, (
                f"Metric '{metric['name']}' still references '{STALE_COLUMN}', "
                "which does not exist in the Hyper file."
            )

    def test_total_miles_metric_present(self, ops_contract: dict[str, Any]) -> None:
        """total_miles metric must exist in contract (mapped to ttl_trf_mi)."""
        names = {m["name"] for m in ops_contract.get("metrics", [])}
        assert "total_miles" in names, (
            "Contract is missing the 'total_miles' metric (mapped to ttl_trf_mi). "
            "join_ops_metrics reads record.get('total_miles', 0) which would be 0 "
            "without this metric."
        )

    def test_total_miles_mapped_to_correct_column(
        self, ops_contract: dict[str, Any]
    ) -> None:
        """total_miles must reference the correct physical column ttl_trf_mi."""
        for metric in ops_contract.get("metrics", []):
            if metric["name"] == "total_miles":
                col = metric.get("column")
                if col is not None:
                    assert col == "ttl_trf_mi", (
                        f"total_miles maps to '{col}', expected 'ttl_trf_mi'."
                    )
                return
        pytest.fail("total_miles metric not found (already caught above).")

    def test_physical_metric_columns_exist_in_hyper(
        self,
        ops_contract: dict[str, Any],
        hyper_columns: dict[str, set[str]],
    ) -> None:
        """Every metric with a 'column' key must exist as a physical column in Hyper."""
        main_cols = hyper_columns.get(EXPECTED_TABLE, set())
        missing: list[str] = []
        for metric in ops_contract.get("metrics", []):
            col = metric.get("column")
            if col and col not in main_cols:
                missing.append(f"{metric['name']} -> {col}")
        assert not missing, (
            "Contract references columns not found in Hyper file:\n"
            + "\n".join(f"  {m}" for m in missing)
        )

    def test_dimension_columns_exist_in_hyper(
        self,
        ops_contract: dict[str, Any],
        hyper_columns: dict[str, set[str]],
    ) -> None:
        """Every dimension column must exist in the Hyper main table."""
        main_cols = hyper_columns.get(EXPECTED_TABLE, set())
        missing: list[str] = []
        for dim in ops_contract.get("dimensions", []):
            col = dim.get("column")
            if col and col not in main_cols:
                missing.append(f"{dim['name']} -> {col}")
        assert not missing, (
            "Contract references dimension columns not found in Hyper file:\n"
            + "\n".join(f"  {m}" for m in missing)
        )


# ---------------------------------------------------------------------------
# Ratios config tests
# ---------------------------------------------------------------------------

class TestRatiosConfig:
    """Verify ops_metrics_ratios_config.yaml is aligned with the live Hyper schema."""

    def test_sql_table_correct(self, ratios_config: dict[str, Any]) -> None:
        """sql_table must reference the current Hyper table name."""
        sql_table = ratios_config.get("sql_table", "")
        assert STALE_TABLE not in sql_table, (
            f"Ratios config sql_table still contains '{STALE_TABLE}'; "
            f"expected {EXPECTED_TABLE!r}."
        )
        assert EXPECTED_TABLE in sql_table, (
            f"Ratios config sql_table expected to contain {EXPECTED_TABLE!r}, "
            f"got {sql_table!r}."
        )

    def test_no_stale_empty_trf_mi_column(self, ratios_config: dict[str, Any]) -> None:
        """No metric entry may reference the non-existent empty_trf_mi column directly."""
        metrics = ratios_config.get("metrics", {})
        for name, defn in metrics.items():
            if not isinstance(defn, dict):
                continue
            col = defn.get("column", "")
            assert col != STALE_COLUMN, (
                f"Ratios config metric '{name}' references '{STALE_COLUMN}' "
                "which does not exist in the Hyper file."
            )
            columns_block = defn.get("columns", {})
            if isinstance(columns_block, dict):
                for key, val in columns_block.items():
                    assert val != STALE_COLUMN, (
                        f"Ratios config metric '{name}.columns.{key}' references "
                        f"'{STALE_COLUMN}' which does not exist in the Hyper file."
                    )

    def test_physical_metric_columns_exist_in_hyper(
        self,
        ratios_config: dict[str, Any],
        hyper_columns: dict[str, set[str]],
    ) -> None:
        """Every column referenced directly in metrics must exist in the Hyper file."""
        main_cols = hyper_columns.get(EXPECTED_TABLE, set())
        missing: list[str] = []
        metrics = ratios_config.get("metrics", {})
        for name, defn in metrics.items():
            if not isinstance(defn, dict):
                continue
            # Direct column reference
            col = defn.get("column")
            if col and col not in main_cols:
                missing.append(f"metrics.{name}.column -> {col}")
            # Columns block values
            columns_block = defn.get("columns", {})
            if isinstance(columns_block, dict):
                for key, val in columns_block.items():
                    if val and val not in main_cols:
                        missing.append(f"metrics.{name}.columns.{key} -> {val}")
        assert not missing, (
            "Ratios config references columns not found in Hyper file:\n"
            + "\n".join(f"  {m}" for m in missing)
        )

    def test_deadhead_formula_uses_total_miles(
        self, ratios_config: dict[str, Any]
    ) -> None:
        """deadhead_pct formula must use ttl_trf_mi (total miles), not empty_trf_mi."""
        dh = ratios_config.get("metrics", {}).get("deadhead_pct", {})
        formula = dh.get("formula", "")
        assert STALE_COLUMN not in formula, (
            f"deadhead_pct formula still references '{STALE_COLUMN}': {formula!r}"
        )
        assert "ttl_trf_mi" in formula, (
            f"deadhead_pct formula does not use 'ttl_trf_mi': {formula!r}. "
            "Expected formula: (ttl_trf_mi - ld_trf_mi) / ttl_trf_mi * 100"
        )


# ---------------------------------------------------------------------------
# Cross-file consistency tests
# ---------------------------------------------------------------------------

class TestCrossFileConsistency:
    """Verify contract and ratios config are mutually consistent."""

    def test_total_miles_in_both_contract_and_ratios(
        self,
        ops_contract: dict[str, Any],
        ratios_config: dict[str, Any],
    ) -> None:
        """total_miles defined in contract should also appear in ratios config."""
        contract_names = {m["name"] for m in ops_contract.get("metrics", [])}
        ratios_names = set(ratios_config.get("metrics", {}).keys())
        if "total_miles" in contract_names:
            assert "total_miles" in ratios_names, (
                "total_miles is in the contract but not in the ratios config."
            )

    def test_deadhead_depends_on_total_and_loaded_miles(
        self, ops_contract: dict[str, Any]
    ) -> None:
        """deadhead_pct must depend on total_miles and loaded_miles (not empty_miles)."""
        for metric in ops_contract.get("metrics", []):
            if metric["name"] == "deadhead_pct":
                depends = metric.get("depends_on", [])
                assert "loaded_miles" in depends, (
                    f"deadhead_pct.depends_on missing 'loaded_miles': {depends}"
                )
                assert "total_miles" in depends, (
                    f"deadhead_pct.depends_on missing 'total_miles': {depends}. "
                    "Should not depend on 'empty_miles' (non-existent column)."
                )
                return
        # If deadhead_pct not present, skip gracefully
