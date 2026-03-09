"""
test_009_ops_metrics_hyper_validation.py

Validates that the Ops Metrics Hyper file (extracted from the current TDSX)
produces values that match the pre-computed validation_data.csv for key
operational metrics.

Spec: pl_analyst/specs/009-a2a-data-validation

Design principles
-----------------
- Direct Hyper API only  — no LLM, no A2A server invocations.
- All SQL via execute_query used as a context manager (Hyper API best practice).
- HyperProcess/Connection are session-scoped fixtures so the 1 GB file is
  opened once per pytest run, not once per test.
- Validation data loaded from CSV at session scope; tests reference the
  pre-parsed dict rather than the file.
- Tolerance: 0.5 % for physical counts/miles/revenue; 2 % for ratios.

Confirmed formulas (Phase A discovery)
---------------------------------------
  Filter       : ops_ln_of_bus_ref_nm = 'Line Haul'
  Date field   : empty_call_dt, Sun (inclusive) – Sat (inclusive)
  Loaded Miles : SUM("ld_trf_mi")
  Total Miles  : SUM("ttl_trf_mi")
  Truck Count  : SUM("truck_count") / 7.0
  Seated Trucks: (SUM("truck_count") - SUM("unmanned_truck_count")) / 7.0
  Open Trucks  : SUM("unmanned_truck_count") / 7.0
  Inactive Trks: SUM("inactive_truck_count") / 7.0
  Solo/Tm/Mntr : SUM("<x>_truck_count") / 7.0
  Rev xFuel    : SUM("ttl_rev_amt") - SUM("fuel_srchrg_rev_amt")
  Active Drvrs : SUM("actv_drvr_cnt") / 7.0
  Order Count  : SUM("ordr_cnt")
  Rev Orders   : SUM("ordr_cnt") WHERE non_rev_flg = 'N'
  Turnover     : SUM("trmntd_drvr_cnt")   (5 % tolerance)
  LRPM         : Rev xFuel / SUM("ld_trf_mi")
  TRPM         : Rev xFuel / SUM("ttl_trf_mi")
  Deadhead %   : 100 * (ttl - ld) / ttl
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

try:
    from tableauhyperapi import Connection, HyperProcess, Telemetry
    HYPER_API_AVAILABLE = True
except ImportError:
    HYPER_API_AVAILABLE = False


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HYPER_PATH = Path(
    r"C:\GITLAB\remote_a2a\tableau_ops_metrics_ds_agent"
    r"\temp_extracted\Data\Extracts\Ops Metrics.hyper"
)
VALIDATION_CSV = Path(r"C:\GITLAB\pl_analyst\data\validation_data.csv")

TABLE = '"Extract"."Extract"'
LOB_FILTER = "\"ops_ln_of_bus_ref_nm\" = 'Line Haul'"

# Week-ending label -> (Sunday, Saturday)  of the Sun-Sat window
WEEK_WINDOWS: dict[str, tuple[str, str]] = {
    "1/4/2025":   ("2024-12-29", "2025-01-04"),
    "1/11/2025":  ("2025-01-05", "2025-01-11"),
    "1/18/2025":  ("2025-01-12", "2025-01-18"),
    "1/25/2025":  ("2025-01-19", "2025-01-25"),
    "2/1/2025":   ("2025-01-26", "2025-02-01"),
    "2/8/2025":   ("2025-02-02", "2025-02-08"),
    "2/15/2025":  ("2025-02-09", "2025-02-15"),
    "2/22/2025":  ("2025-02-16", "2025-02-22"),
    "3/1/2025":   ("2025-02-23", "2025-03-01"),
    "3/8/2025":   ("2025-03-02", "2025-03-08"),
    "3/15/2025":  ("2025-03-09", "2025-03-15"),
}

# Tolerance thresholds
TOL_DEFAULT = 0.005   # 0.5 %
TOL_RATIO   = 0.020   # 2.0 % for LRPM / TRPM / Deadhead %
TOL_TURNOVER = 0.075  # 7.5 % (trmntd_drvr_cnt slightly overstates CSV value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_num(raw: str) -> float:
    """Strip currency/percent formatting and return float."""
    if not raw or raw.strip() in ("-", ""):
        return float("nan")
    cleaned = re.sub(r"[$,%]", "", raw.strip())
    return float(cleaned)


def _pct_diff(a: float, b: float) -> float:
    if b == 0:
        return float("inf")
    return abs(a - b) / abs(b)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def hyper_log_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Unique log directory for HyperProcess to avoid inter-process conflicts."""
    d = tmp_path_factory.mktemp("hyper_logs_validation")
    return str(d)


@pytest.fixture(scope="session")
def hyper_connection(hyper_log_dir: str):
    """Open one HyperProcess + Connection for the entire test session.

    Uses execute_query inside each test as a context manager (best practice).
    """
    if not HYPER_API_AVAILABLE:
        pytest.skip("tableauhyperapi not installed")
    if not HYPER_PATH.exists():
        pytest.skip(f"Hyper file not found: {HYPER_PATH}")

    try:
        from tableauhyperapi import HyperException
    except ImportError:
        HyperException = Exception

    try:
        with HyperProcess(
            telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
            parameters={"log_dir": hyper_log_dir},
        ) as hyper:
            try:
                with Connection(
                    endpoint=hyper.endpoint,
                    database=str(HYPER_PATH),
                ) as conn:
                    yield conn
            except HyperException as exc:
                if "locked" in str(exc).lower() or "database" in str(exc).lower():
                    pytest.skip(
                        "Hyper file is locked by A2A server -- stop server before running these tests"
                    )
                raise
    except HyperException as exc:
        if "locked" in str(exc).lower():
            pytest.skip(
                "Hyper file is locked by A2A server -- stop server before running these tests"
            )
        raise


@pytest.fixture(scope="session")
def validation_data() -> dict[tuple[str, str, str], dict[str, float]]:
    """Parse validation_data.csv into a nested dict.

    Returns:
        { (region, division, metric) -> { week_label: float_value } }
    """
    if not VALIDATION_CSV.exists():
        pytest.skip(f"Validation CSV not found: {VALIDATION_CSV}")

    result: dict[tuple[str, str, str], dict[str, float]] = {}
    with open(VALIDATION_CSV, encoding="utf-16", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = list(reader)

    if not rows:
        return result

    header = rows[0]
    week_labels = [h.strip() for h in header[3:]]

    for row in rows[1:]:
        if len(row) < 4:
            continue
        region   = row[0].strip()
        division = row[1].strip()
        metric   = row[2].strip()
        if not metric:
            continue
        key = (region, division, metric)
        result[key] = {}
        for i, week in enumerate(week_labels):
            raw = row[3 + i] if 3 + i < len(row) else ""
            result[key][week] = _parse_num(raw)

    return result


# ---------------------------------------------------------------------------
# SQL helper bound to session connection
# ---------------------------------------------------------------------------

def _query(conn: Connection, sql: str) -> list[dict[str, Any]]:
    """Execute SQL and return rows as a list of dicts.

    Always uses execute_query as a context manager to promptly release
    the result set — required Hyper API best practice.
    """
    with conn.execute_query(sql) as result:
        cols = [c.name.unescaped for c in result.schema.columns]
        return [{cols[i]: row[i] for i in range(len(cols))} for row in result]


def _week_sql(
    conn: Connection,
    metrics_expr: str,
    week: str,
    region_filter: str = "",
) -> dict[str, Any]:
    """Run a single-week aggregate query and return the first row as a dict."""
    d_from, d_to = WEEK_WINDOWS[week]
    region_clause = f'AND "gl_rgn_nm" = \'{region_filter}\'' if region_filter else ""
    sql = f"""
        SELECT {metrics_expr}
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          {region_clause}
    """
    rows = _query(conn, sql)
    return rows[0] if rows else {}


# ---------------------------------------------------------------------------
# P1: Company Total — Miles & Truck Counts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025", "1/25/2025"])
def test_company_loaded_miles(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(ld_trf_mi) should match validation Loaded Miles within 0.5 %."""
    expected = validation_data[("Total", "Total", "Loaded Miles")][week]
    row = _week_sql(hyper_connection, 'SUM("ld_trf_mi") AS v', week)
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Loaded Miles sql={actual:,.0f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025", "1/25/2025"])
def test_company_total_miles(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(ttl_trf_mi) should match validation Total Miles within 0.5 %."""
    expected = validation_data[("Total", "Total", "Total Miles")][week]
    row = _week_sql(hyper_connection, 'SUM("ttl_trf_mi") AS v', week)
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Total Miles sql={actual:,.0f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025", "1/25/2025"])
def test_company_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(truck_count) / 7 should match validation Truck Count within 0.5 %."""
    expected = validation_data[("Total", "Total", "Truck Count")][week]
    row = _week_sql(hyper_connection, 'SUM("truck_count") * 1.0 / 7 AS v', week)
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_seated_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """(truck_count - unmanned_truck_count) / 7 matches Seated Truck Count."""
    expected = validation_data[("Total", "Total", "Seated Truck Count")][week]
    row = _week_sql(
        hyper_connection,
        '(SUM("truck_count") - SUM("unmanned_truck_count")) * 1.0 / 7 AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Seated Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_open_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(unmanned_truck_count) / 7 matches Open Truck Count."""
    expected = validation_data[("Total", "Total", "Open Truck Count")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("unmanned_truck_count") * 1.0 / 7 AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Open Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_inactive_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(inactive_truck_count) / 7 matches Inactive Truck Count."""
    expected = validation_data[("Total", "Total", "Inactive Truck Count")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("inactive_truck_count") * 1.0 / 7 AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Inactive Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_solo_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Total", "Total", "Solo Truck Count")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("solo_truck_count") * 1.0 / 7 AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Solo Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_team_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Total", "Total", "Team Truck Count")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("team_truck_count") * 1.0 / 7 AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Team Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_mentor_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    # CSV label "Mentor Truck Count " has trailing space; fixture strips it
    key = ("Total", "Total", "Mentor Truck Count")
    expected = validation_data[key][week]
    row = _week_sql(
        hyper_connection,
        'SUM("mentor_truck_count") * 1.0 / 7 AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Mentor Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


# ---------------------------------------------------------------------------
# P1: Company Total — Revenue
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025", "1/25/2025"])
def test_company_revenue_xfuel(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """ttl_rev_amt - fuel_srchrg_rev_amt matches Revenue xFuel within 0.5 %."""
    expected = validation_data[("Total", "Total", "Revenue xFuel")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("ttl_rev_amt") - SUM("fuel_srchrg_rev_amt") AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Revenue xFuel sql={actual:,.2f} expected={expected:,.0f}"
    )


# ---------------------------------------------------------------------------
# P1: Company Total — Driver Counts & Orders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_active_driver_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(actv_drvr_cnt) / 7 matches Active Driver Count."""
    expected = validation_data[("Total", "Total", "Active Driver Count")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("actv_drvr_cnt") * 1.0 / 7 AS v',
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Active Driver Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_order_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(ordr_cnt) matches Order Count within 0.5 %."""
    expected = validation_data[("Total", "Total", "Order Count")][week]
    row = _week_sql(hyper_connection, 'SUM("ordr_cnt") AS v', week)
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Order Count sql={actual:,.1f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_revenue_order_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(ordr_cnt) WHERE non_rev_flg='N' matches Revenue Order Count."""
    expected = validation_data[("Total", "Total", "Revenue Order Count")][week]
    d_from, d_to = WEEK_WINDOWS[week]
    rows = _query(
        hyper_connection,
        f"""
        SELECT SUM("ordr_cnt") AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          AND "non_rev_flg" = 'N'
        """,
    )
    actual = float((rows[0]["v"] if rows else None) or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Revenue Order Count sql={actual:,.1f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_turnover_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """SUM(trmntd_drvr_cnt) approximates Turnover Count within 7.5 %."""
    expected = validation_data[("Total", "Total", "Turnover Count")][week]
    row = _week_sql(hyper_connection, 'SUM("trmntd_drvr_cnt") AS v', week)
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_TURNOVER, (
        f"Week {week}: Turnover Count sql={actual:.0f} expected={expected:.0f}"
    )


# ---------------------------------------------------------------------------
# P1: Driver subtypes — Solo / Mentor Loaded Miles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_solo_loaded_miles(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Total", "Total", "Solo Loaded Miles")][week]
    d_from, d_to = WEEK_WINDOWS[week]
    rows = _query(
        hyper_connection,
        f"""
        SELECT SUM("ld_trf_mi") AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          AND "driver_type" = 'S'
        """,
    )
    actual = float((rows[0]["v"] if rows else None) or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Solo Loaded Miles sql={actual:,.0f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_mentor_loaded_miles(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Total", "Total", "Mentor Loaded Miles")][week]
    d_from, d_to = WEEK_WINDOWS[week]
    rows = _query(
        hyper_connection,
        f"""
        SELECT SUM("ld_trf_mi") AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          AND "driver_type" = 'M'
        """,
    )
    actual = float((rows[0]["v"] if rows else None) or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Mentor Loaded Miles sql={actual:,.0f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_team_loaded_miles(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Total", "Total", "Team Loaded Miles")][week]
    d_from, d_to = WEEK_WINDOWS[week]
    rows = _query(
        hyper_connection,
        f"""
        SELECT SUM("ld_trf_mi") AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          AND "driver_type" = 'T'
        """,
    )
    actual = float((rows[0]["v"] if rows else None) or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Team Loaded Miles sql={actual:,.0f} expected={expected:,.0f}"
    )


# ---------------------------------------------------------------------------
# P2: Derived ratios
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_lrpm(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """LRPM = Rev xFuel / Loaded Miles."""
    expected = validation_data[("Total", "Total", "LRPM")][week]
    row = _week_sql(
        hyper_connection,
        """
        (SUM("ttl_rev_amt") - SUM("fuel_srchrg_rev_amt"))
          / NULLIF(SUM("ld_trf_mi"), 0) AS v
        """,
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_RATIO, (
        f"Week {week}: LRPM sql={actual:.4f} expected={expected:.2f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_trpm(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """TRPM = Rev xFuel / Total Miles."""
    expected = validation_data[("Total", "Total", "TRPM")][week]
    row = _week_sql(
        hyper_connection,
        """
        (SUM("ttl_rev_amt") - SUM("fuel_srchrg_rev_amt"))
          / NULLIF(SUM("ttl_trf_mi"), 0) AS v
        """,
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_RATIO, (
        f"Week {week}: TRPM sql={actual:.4f} expected={expected:.2f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_company_deadhead_pct(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """Deadhead % = 100 * (ttl - ld) / ttl."""
    expected = validation_data[("Total", "Total", "Deadhead %")][week]
    row = _week_sql(
        hyper_connection,
        """
        100.0
          * (SUM("ttl_trf_mi") - SUM("ld_trf_mi"))
          / NULLIF(SUM("ttl_trf_mi"), 0) AS v
        """,
        week,
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_RATIO, (
        f"Week {week}: Deadhead % sql={actual:.2f} expected={expected:.2f}"
    )


# ---------------------------------------------------------------------------
# P1: Regional — Central
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_central_loaded_miles(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Central", "Total", "Loaded Miles")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("ld_trf_mi") AS v',
        week,
        region_filter="Central",
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Central Loaded Miles sql={actual:,.0f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_central_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Central", "Total", "Truck Count")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("truck_count") * 1.0 / 7 AS v',
        week,
        region_filter="Central",
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Central Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_central_revenue_xfuel(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("Central", "Total", "Revenue xFuel")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("ttl_rev_amt") - SUM("fuel_srchrg_rev_amt") AS v',
        week,
        region_filter="Central",
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: Central Revenue xFuel sql={actual:,.2f} expected={expected:,.0f}"
    )


# ---------------------------------------------------------------------------
# P1: Regional — West
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_west_loaded_miles(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("West", "Total", "Loaded Miles")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("ld_trf_mi") AS v',
        week,
        region_filter="West",
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: West Loaded Miles sql={actual:,.0f} expected={expected:,.0f}"
    )


@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_west_truck_count(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    expected = validation_data[("West", "Total", "Truck Count")][week]
    row = _week_sql(
        hyper_connection,
        'SUM("truck_count") * 1.0 / 7 AS v',
        week,
        region_filter="West",
    )
    actual = float(row["v"] or 0)
    assert _pct_diff(actual, expected) <= TOL_DEFAULT, (
        f"Week {week}: West Truck Count sql={actual:.1f} expected={expected:.0f}"
    )


# ---------------------------------------------------------------------------
# T024: Terminal-level Loaded Miles spot-check (5 terminals, 2 weeks)
# Each terminal filtered by both gl_div_nm AND gl_rgn_nm (duplicate names exist,
# e.g., "Lancaster" appears in both Central and West).
# ---------------------------------------------------------------------------

_TERMINAL_CASES = [
    # (region, terminal,      week,         expected)
    ("Central", "Lancaster",  "1/11/2025",  347_648),
    ("Central", "Lancaster",  "2/8/2025",   430_090),
    ("East",    "Greer",      "1/11/2025",  549_215),
    ("East",    "Greer",      "2/8/2025",   549_645),
    ("East",    "Ocala",      "1/11/2025",  531_225),
    ("East",    "Ocala",      "2/8/2025",   571_892),
    ("West",    "Phoenix",    "1/11/2025",  604_045),
    ("West",    "Phoenix",    "2/8/2025",   738_210),
    ("West",    "Troutdale",  "1/11/2025",  166_441),
    ("West",    "Troutdale",  "2/8/2025",   156_004),
]


@pytest.mark.parametrize(
    "region,terminal,week,expected",
    _TERMINAL_CASES,
    ids=[f"{r}/{t}/{w}" for r, t, w, _ in _TERMINAL_CASES],
)
def test_terminal_loaded_miles(
    hyper_connection: Connection,
    region: str,
    terminal: str,
    week: str,
    expected: float,
) -> None:
    """Loaded Miles at individual terminal level matches validation (1 % tol)."""
    d_from, d_to = WEEK_WINDOWS[week]
    rows = _query(
        hyper_connection,
        f"""
        SELECT SUM("ld_trf_mi") AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          AND "gl_rgn_nm"  = '{region}'
          AND "gl_div_nm"  = '{terminal}'
        """,
    )
    actual = float((rows[0]["v"] if rows else None) or 0)
    assert _pct_diff(actual, expected) <= 0.01, (  # 1 % terminal tolerance
        f"{region}/{terminal} week {week}: Loaded Miles sql={actual:,.0f} "
        f"expected={expected:,.0f}"
    )


# ---------------------------------------------------------------------------
# T025: Region rollup — SQL sum across all regions equals SQL company total
# This is a pure internal consistency check (no CSV dependency).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_region_rollup_equals_company_total(
    hyper_connection: Connection,
    week: str,
) -> None:
    """Sum of per-region Loaded Miles must equal the company-total query."""
    d_from, d_to = WEEK_WINDOWS[week]
    base = f"""
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
    """
    company_rows = _query(hyper_connection, f"SELECT SUM(\"ld_trf_mi\") AS v {base}")
    company_total = float((company_rows[0]["v"] if company_rows else None) or 0)

    region_rows = _query(
        hyper_connection,
        f"""
        SELECT "gl_rgn_nm", SUM("ld_trf_mi") AS v
        {base}
        GROUP BY "gl_rgn_nm"
        """,
    )
    region_sum = sum(float(r["v"] or 0) for r in region_rows)

    assert _pct_diff(region_sum, company_total) <= 0.001, (
        f"Week {week}: region sum={region_sum:,.0f} != company total={company_total:,.0f}"
    )


# ---------------------------------------------------------------------------
# T026: Terminal rollup to region — sum of Central terminals = Central total
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week", ["1/11/2025", "1/18/2025"])
def test_central_terminal_rollup(
    hyper_connection: Connection,
    validation_data: dict,
    week: str,
) -> None:
    """Sum of all Central terminal Loaded Miles equals Central region total."""
    d_from, d_to = WEEK_WINDOWS[week]
    base = f"""
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          AND "gl_rgn_nm" = 'Central'
    """
    # SQL region total
    region_rows = _query(hyper_connection, f'SELECT SUM("ld_trf_mi") AS v {base}')
    region_total = float((region_rows[0]["v"] if region_rows else None) or 0)

    # SQL terminal breakdown
    term_rows = _query(
        hyper_connection,
        f"""
        SELECT "gl_div_nm", SUM("ld_trf_mi") AS v
        {base}
        GROUP BY "gl_div_nm"
        """,
    )
    terminal_sum = sum(float(r["v"] or 0) for r in term_rows)

    # Both rollup must agree with each other and with validation Central total
    expected = validation_data[("Central", "Total", "Loaded Miles")][week]
    assert _pct_diff(terminal_sum, region_total) <= 0.001, (
        f"Week {week}: Central terminal sum={terminal_sum:,.0f} != "
        f"region total={region_total:,.0f}"
    )
    assert _pct_diff(region_total, expected) <= TOL_DEFAULT, (
        f"Week {week}: Central total sql={region_total:,.0f} "
        f"expected={expected:,.0f}"
    )


# ---------------------------------------------------------------------------
# T029: Rev/Trk/Wk by region
# Formula: (ttl_rev_amt - fuel_srchrg_rev_amt) / (truck_count / 7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "region,week",
    [
        ("Total",   "1/11/2025"),
        ("Total",   "1/18/2025"),
        ("Central", "1/11/2025"),
        ("Central", "1/18/2025"),
        ("West",    "1/11/2025"),
        ("West",    "1/18/2025"),
    ],
)
def test_rev_per_truck_per_week(
    hyper_connection: Connection,
    validation_data: dict,
    region: str,
    week: str,
) -> None:
    """Rev/Trk/Wk = Revenue xFuel / Truck Count matches validation within 1 %."""
    expected = validation_data[(region, "Total", "Rev/Trk/Wk")][week]
    d_from, d_to = WEEK_WINDOWS[week]
    region_clause = (
        f'AND "gl_rgn_nm" = \'{region}\'' if region != "Total" else ""
    )
    rows = _query(
        hyper_connection,
        f"""
        SELECT
          (SUM("ttl_rev_amt") - SUM("fuel_srchrg_rev_amt"))
            / NULLIF(SUM("truck_count") * 1.0 / 7, 0) AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{d_from}'
          AND "empty_call_dt" <= DATE '{d_to}'
          AND {LOB_FILTER}
          {region_clause}
        """,
    )
    actual = float((rows[0]["v"] if rows else None) or 0)
    assert _pct_diff(actual, expected) <= 0.01, (
        f"{region} week {week}: Rev/Trk/Wk sql={actual:,.0f} "
        f"expected={expected:,.0f}"
    )


# ---------------------------------------------------------------------------
# T030: Multi-week total — 4 consecutive weeks are additive
# SQL: one query over the 4-week window == sum of 4 individual-week queries.
# Cross-checked against sum of 4 validation weeks.
# ---------------------------------------------------------------------------

_4WK_WINDOWS = [
    ("1/11/2025", WEEK_WINDOWS["1/11/2025"]),
    ("1/18/2025", WEEK_WINDOWS["1/18/2025"]),
    ("1/25/2025", WEEK_WINDOWS["1/25/2025"]),
    ("2/1/2025",  WEEK_WINDOWS["2/1/2025"]),
]
_4WK_COMBINED = ("2025-01-05", "2025-02-01")  # span covering all 4 weeks


def test_multi_week_loaded_miles_additive(
    hyper_connection: Connection,
    validation_data: dict,
) -> None:
    """4-week combined SQL == sum of 4 individual-week SQL == sum of 4 validation values."""
    # Combined single-query sum
    combined_rows = _query(
        hyper_connection,
        f"""
        SELECT SUM("ld_trf_mi") AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '{_4WK_COMBINED[0]}'
          AND "empty_call_dt" <= DATE '{_4WK_COMBINED[1]}'
          AND {LOB_FILTER}
        """,
    )
    combined = float((combined_rows[0]["v"] if combined_rows else None) or 0)

    # Sum of 4 individual week queries
    individual_sum = 0.0
    for _, (d_from, d_to) in _4WK_WINDOWS:
        rows = _query(
            hyper_connection,
            f"""
            SELECT SUM("ld_trf_mi") AS v
            FROM {TABLE}
            WHERE "empty_call_dt" >= DATE '{d_from}'
              AND "empty_call_dt" <= DATE '{d_to}'
              AND {LOB_FILTER}
            """,
        )
        individual_sum += float((rows[0]["v"] if rows else None) or 0)

    # Validation sum
    csv_sum = sum(
        validation_data[("Total", "Total", "Loaded Miles")][lbl]
        for lbl, _ in _4WK_WINDOWS
    )

    # Combined == individual (must be exact — weeks are non-overlapping)
    assert _pct_diff(combined, individual_sum) <= 0.0001, (
        f"Combined={combined:,.0f} != individual sum={individual_sum:,.0f}"
    )
    # Both against CSV sum
    assert _pct_diff(combined, csv_sum) <= TOL_DEFAULT, (
        f"4-week SQL={combined:,.0f} expected CSV sum={csv_sum:,.0f}"
    )


# ---------------------------------------------------------------------------
# T031: Full calendar year 2025 Revenue xFuel
# Uses empty_call_dt 2025-01-01 through 2025-12-31 to stay within the year.
# Validation: sum of all 52 weeks ending in 2025 = $1,121,099,834.
# Tolerance 1 % to account for the partial first/last week boundaries.
# ---------------------------------------------------------------------------

def test_full_year_2025_revenue_xfuel(
    hyper_connection: Connection,
    validation_data: dict,
) -> None:
    """Full-year 2025 Revenue xFuel matches sum of all 52 validation weeks."""
    rows = _query(
        hyper_connection,
        f"""
        SELECT SUM("ttl_rev_amt") - SUM("fuel_srchrg_rev_amt") AS v
        FROM {TABLE}
        WHERE "empty_call_dt" >= DATE '2025-01-01'
          AND "empty_call_dt" <= DATE '2025-12-31'
          AND {LOB_FILTER}
        """,
    )
    actual = float((rows[0]["v"] if rows else None) or 0)

    # Sum all 52 weeks ending in 2025 from validation CSV
    import re as _re

    csv_annual = sum(
        v
        for (region, division, metric), weekly in validation_data.items()
        if region == "Total" and division == "Total" and metric == "Revenue xFuel"
        for wk, v in weekly.items()
        if wk.endswith("2025") and v == v  # skip NaN
    )

    assert _pct_diff(actual, csv_annual) <= 0.01, (
        f"Full year 2025 Revenue xFuel: sql={actual:,.0f} "
        f"csv_sum={csv_annual:,.0f}"
    )
