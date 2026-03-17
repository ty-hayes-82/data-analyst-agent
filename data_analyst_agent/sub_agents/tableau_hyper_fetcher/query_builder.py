"""HyperQueryBuilder: Generates Tableau Hyper SQL for the TableauHyperFetcher.

The goal is to generate a SQL string that:
  1. Buckets data by month-end or week-end based on configuration.
  2. Filters raw data by LOB, Terminal, etc.
  3. SUMs the declared metric columns.
  4. Computes any derived metrics as SQL expressions in the outer SELECT.
  5. Applies optional WHERE clauses for date range and filter-column values.

The generated SQL is standard Hyper/Postgres dialect with all identifiers
double-quoted to handle spaces and reserved words.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import pandas as pd

from .loader_config import AggregationRule, HyperLoaderConfig


class HyperQueryBuilder:
    """Builder for generating complex Hyper SQL from a loader configuration."""

    def __init__(self, cfg: HyperLoaderConfig):
        self._cfg = cfg

    def build_query(
        self,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        filters: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """Construct the full SQL query based on configuration and runtime filters.

        Args:
            date_start: ISO date string for the start of the range (inclusive).
            date_end:   ISO date string for the end of the range (inclusive).
            filters:    Map of physical column name -> list of allowed values.

        Returns:
            A SQL string ready to pass to ``HyperConnectionManager.execute_query()``.
        """
        agg = self._cfg.aggregation
        table = self._quote_table(self._cfg.hyper.default_table)

        if agg is None:
            # No aggregation -- simple SELECT * with optional filters
            where = self._build_where_clause(
                agg=None,
                date_start=date_start,
                date_end=date_end,
                filters=filters or {},
            )
            sql = f"SELECT * FROM {table}"
            if where:
                sql += f" WHERE {where}"
            return sql

        period_expr = self._period_expression(agg)
        period_alias = self._q(agg.period_alias)

        group_cols_sql = [self._q(c) for c in agg.group_by_columns]
        
        # We use _q for the expression part and always wrap the alias in quotes.
        sum_cols_sql = [
            f"SUM({self._qcol(c)}) AS \"{c}\"" for c in agg.sum_columns
        ]
        avg_cols_sql = [
            f"AVG({self._qcol(c)}) AS \"{c}\"" for c in agg.avg_columns
        ]
        count_distinct_cols_sql = [
            f"COUNT(DISTINCT {self._qcol(c)}) AS \"{c}\"" for c in agg.count_distinct_columns
        ]

        where = self._build_where_clause(
            agg=agg,
            date_start=date_start,
            date_end=date_end,
            filters=filters or {},
        )

        # Inner query: period bucketing + raw aggregation
        inner_select_parts = (
            [f"{period_expr} AS {period_alias}"]
            + group_cols_sql
            + sum_cols_sql
            + avg_cols_sql
            + count_distinct_cols_sql
        )
        inner_select = ",\n    ".join(inner_select_parts)

        group_by_parts = [period_expr] + group_cols_sql
        group_by = ",\n    ".join(group_by_parts)

        inner_sql = f"SELECT\n    {inner_select}\nFROM {table}"
        if where:
            inner_sql += f"\nWHERE {where}"
        inner_sql += f"\nGROUP BY\n    {group_by}"

        # Outer query: pass through all inner columns + derived metrics
        if not agg.derived_metrics:
            return inner_sql

        outer_pass_through = (
            [period_alias]
            + group_cols_sql
            + [f'"{c}"' for c in agg.sum_columns]
            + [f'"{c}"' for c in agg.avg_columns]
            + [f'"{c}"' for c in agg.count_distinct_columns]
        )
        derived_exprs = [
            f"{m.sql} AS \"{m.name}\"" for m in agg.derived_metrics
        ]
        outer_select_parts = outer_pass_through + derived_exprs
        outer_select = ",\n    ".join(outer_select_parts)

        order_first = group_cols_sql[0] if group_cols_sql else period_alias
        sql = (
            f"SELECT\n    {outer_select}\n"
            f"FROM (\n{self._indent(inner_sql)}\n) AS _inner\n"
            f"ORDER BY {period_alias}, {order_first}"
        )
        return sql

    def build_bulk_export_sql(
        self,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        filters: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """Return a query for bulk exporting data to CSV via STDOUT."""
        query = self.build_query(date_start, date_end, filters)
        return f"COPY ({query}) TO STDOUT (FORMAT CSV, HEADER TRUE)"

    def build_schema_query(self) -> str:
        """Return a query that returns zero rows but exposes the full schema."""
        table = self._quote_table(self._cfg.hyper.default_table)
        return f"SELECT * FROM {table} LIMIT 0"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _q(identifier: str) -> str:
        """Double-quote a column or alias identifier, unless it looks like an expression."""
        if not identifier:
            return ""
        # If already quoted, return as is
        if identifier.startswith('"') and identifier.endswith('"'):
            return identifier
        
        # If it's purely alphanumeric + underscores + spaces, it's likely an identifier that needs quoting
        if re.match(r'^[a-zA-Z0-9_ ]+$', identifier):
            return '"' + identifier.replace('"', '""') + '"'
            
        # Otherwise, assume it's a SQL expression (contains (, /, +, -, etc.)
        return identifier

    @staticmethod
    def _qcol(column_name: str) -> str:
        """Always double-quote a column name. Use for identifiers from config."""
        if not column_name:
            return ""
        if column_name.startswith('"') and column_name.endswith('"'):
            return column_name
        return '"' + column_name.replace('"', '""') + '"'

    @staticmethod
    def _quote_table(table_spec: str) -> str:
        """Quote a table specification like ``Extract.Extract``.

        Accepts forms:
          - ``"Extract"."Extract"``  (already quoted)
          - ``Extract.Extract``
          - ``Extract``
        """
        if '"' in table_spec:
            return table_spec
        parts = table_spec.split(".")
        return ".".join(f'"{p}"' for p in parts)

    def _indent(self, sql: str, spaces: int = 4) -> str:
        """Indent a multi-line SQL string for readability inside subqueries."""
        pad = " " * spaces
        return pad + sql.replace("\n", "\n" + pad)

    def _period_expression(self, agg: AggregationRule) -> str:
        """Generate the SQL expression for bucketing dates into month-end or week-end."""
        if agg.date_column:
            dc = self._q(agg.date_column)
            if agg.period_type == "month_end":
                # Move to 1st of next month, subtract 1 day
                return (
                    f"CAST(DATE_TRUNC('month', {dc}) + INTERVAL '1 month' "
                    f"- INTERVAL '1 day' AS DATE)"
                )
            if agg.period_type == "week_end":
                # Saturday of the ISO week containing date_col
                # DOW: Sunday=0 ... Saturday=6
                return (
                    f"CAST({dc} + ((6 - EXTRACT(DOW FROM {dc})) "
                    f"* INTERVAL '1 day') AS DATE)"
                )
            # "day" -- just cast to DATE
            return f"CAST({dc} AS DATE)"

        if agg.year_column and agg.month_column:
            yc = self._q(agg.year_column)
            mc = self._q(agg.month_column)
            # Build ISO string 'YYYY-MM-01', cast to date, then move to month-end.
            # Handle adjustment periods (13, 14) by capping at 12 for date construction.
            return (
                f"CAST(DATE_TRUNC('month', CAST(CAST({yc} AS VARCHAR) || '-' || "
                f"CAST(CASE WHEN CAST({mc} AS INTEGER) > 12 THEN 12 ELSE CAST({mc} AS INTEGER) END AS VARCHAR) || '-01' AS DATE)) "
                f"+ INTERVAL '1 month' - INTERVAL '1 day' AS DATE)"
            )

        raise ValueError(
            "AggregationRule must specify either date_column or both year_column and month_column."
        )

    def _build_where_clause(
        self,
        agg: Optional[AggregationRule],
        date_start: Optional[str],
        date_end: Optional[str],
        filters: Dict[str, List[str]],
    ) -> str:
        """Build a WHERE clause string (without the WHERE keyword).

        Returns an empty string if there are no conditions.
        """
        conditions: List[str] = []

        if agg and (date_start or date_end):
            if agg.date_column:
                dc = self._q(agg.date_column)
                # Filter out extreme dates often used as placeholders (9999-12-31)
                conditions.append(f"{dc} < DATE '2100-01-01'")
                if date_start:
                    conditions.append(f"{dc} >= DATE '{self._esc_val(date_start)}'")
                if date_end:
                    conditions.append(f"{dc} <= DATE '{self._esc_val(date_end)}'")
            elif agg.year_column and agg.month_column:
                # Handle year/month integer filters
                yc = self._q(agg.year_column)
                mc = self._q(agg.month_column)
                conditions.append(f"CAST({yc} AS INTEGER) < 2100")
                if date_start:
                    try:
                        dt = pd.to_datetime(date_start)
                        conditions.append(
                            f"(CAST({yc} AS INTEGER) > {dt.year} OR "
                            f"(CAST({yc} AS INTEGER) = {dt.year} AND CAST({mc} AS INTEGER) >= {dt.month}))"
                        )
                    except Exception:
                        pass
                if date_end:
                    try:
                        dt = pd.to_datetime(date_end)
                        conditions.append(
                            f"(CAST({yc} AS INTEGER) < {dt.year} OR "
                            f"(CAST({yc} AS INTEGER) = {dt.year} AND CAST({mc} AS INTEGER) <= {dt.month}))"
                        )
                    except Exception:
                        pass

        for col, values in (filters or {}).items():
            if not values:
                continue
            qc = self._q(col)
            quoted_vals = ", ".join(f"'{self._esc_val(v)}'" for v in values)
            if len(values) == 1:
                conditions.append(f"{qc} = '{self._esc_val(values[0])}'")
            else:
                conditions.append(f"{qc} IN ({quoted_vals})")

        return "\nAND ".join(conditions)

    @staticmethod
    def _esc_val(val: str) -> str:
        """Escape single quotes in a SQL literal value."""
        return str(val).replace("'", "''")
