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
from typing import Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from .loader_config import AggregationRule, HyperLoaderConfig

if TYPE_CHECKING:
    from .ranked_subset import RankedSubsetSpec


class HyperQueryBuilder:
    """Builder for generating complex Hyper SQL from a loader configuration."""

    def __init__(self, cfg: HyperLoaderConfig):
        self._cfg = cfg

    def build_query(
        self,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        filters: Optional[Dict[str, List[str]]] = None,
        ranked_spec: Optional["RankedSubsetSpec"] = None,
    ) -> str:
        """Construct the full SQL query based on configuration and runtime filters.

        Args:
            date_start: ISO date string for the start of the range (inclusive).
            date_end:   ISO date string for the end of the range (inclusive).
            filters:    Map of physical column name -> list of allowed values.
            ranked_spec: Optional contract-resolved ranked subset (CTE + join).

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

        where_kwargs = dict(
            agg=agg,
            date_start=date_start,
            date_end=date_end,
            filters=filters or {},
        )
        where = self._build_where_clause(**where_kwargs)

        if ranked_spec is not None:
            where_cte = self._build_where_clause(**where_kwargs, table_alias=None)
            where_main = self._build_where_clause(**where_kwargs, table_alias="_f")
            inner_sql = self._build_ranked_aggregation_sql(
                agg=agg,
                table=table,
                where_cte=where_cte,
                where_main=where_main,
                ranked_spec=ranked_spec,
            )
        else:
            period_expr = self._period_expression(agg)
            period_alias = self._q(agg.period_alias)

            group_cols_sql = [self._q(c) for c in agg.group_by_columns]

            sum_cols_sql = [
                f"SUM({self._qcol(c)}) AS \"{c}\"" for c in agg.sum_columns
            ]
            avg_cols_sql = [
                f"AVG({self._qcol(c)}) AS \"{c}\"" for c in agg.avg_columns
            ]
            count_distinct_cols_sql = [
                f"COUNT(DISTINCT {self._qcol(c)}) AS \"{c}\"" for c in agg.count_distinct_columns
            ]

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

        period_alias = self._q(agg.period_alias)
        group_cols_sql = [self._q(c) for c in agg.group_by_columns]

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

    def _period_expression(self, agg: AggregationRule, table_alias: Optional[str] = None) -> str:
        """Generate the SQL expression for bucketing dates into month-end or week-end."""
        if agg.date_column:
            dc = self._q(agg.date_column)
            if table_alias:
                dc = f"{table_alias}.{dc}"
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

    @staticmethod
    def _qualify_table_column(table_alias: Optional[str], quoted_identifier: str) -> str:
        if not table_alias:
            return quoted_identifier
        return f"{table_alias}.{quoted_identifier}"

    def _build_ranked_ctes(
        self,
        table: str,
        where_cte: str,
        ranked_spec: "RankedSubsetSpec",
    ) -> str:
        """Return comma-separated CTE definitions for 2- or 3-level ranked slice."""
        if ranked_spec.is_three_level:
            return self._build_ranked_ctes_three_level(table, where_cte, ranked_spec)
        return self._build_ranked_ctes_two_level(table, where_cte, ranked_spec)

    def _build_ranked_ctes_two_level(
        self,
        table: str,
        where_cte: str,
        ranked_spec: "RankedSubsetSpec",
    ) -> str:
        c0 = self._qcol(ranked_spec.column_level_0)
        c1 = self._qcol(ranked_spec.column_level_1)
        rcc = self._qcol(ranked_spec.rank_col)
        n0 = int(ranked_spec.top_level_0)
        n1 = int(ranked_spec.top_level_1_per_level_0)

        cte_where = f"WHERE {where_cte}" if where_cte else ""

        ranked_top_level_0 = (
            f"ranked_top_level_0 AS (\n"
            f"    SELECT l0_inner AS l0 FROM (\n"
            f"        SELECT {c0} AS l0_inner, SUM({rcc}) AS _rs\n"
            f"        FROM {table}\n"
            f"        {cte_where}\n"
            f"        GROUP BY 1\n"
            f"        ORDER BY 2 DESC NULLS LAST\n"
            f"        LIMIT {n0}\n"
            f"    ) AS _sub0\n"
            f")"
        )

        l0_in = f"{c0} IN (SELECT l0 FROM ranked_top_level_0)"
        if where_cte:
            agg_where = f"WHERE {where_cte}\n    AND {l0_in}"
        else:
            agg_where = f"WHERE {l0_in}"

        agg_level_0_level_1 = (
            f"agg_level_0_level_1 AS (\n"
            f"    SELECT {c0} AS l0, {c1} AS l1, SUM({rcc}) AS _te\n"
            f"    FROM {table}\n"
            f"    {agg_where}\n"
            f"    GROUP BY 1, 2\n"
            f")"
        )

        allowed_level_0_level_1 = (
            f"allowed_level_0_level_1 AS (\n"
            f"    SELECT l0, l1 FROM (\n"
            f"        SELECT l0, l1, ROW_NUMBER() OVER (PARTITION BY l0 ORDER BY _te DESC NULLS LAST) AS rn\n"
            f"        FROM agg_level_0_level_1\n"
            f"    ) AS _z\n"
            f"    WHERE rn <= {n1}\n"
            f")"
        )

        return ",\n".join([ranked_top_level_0, agg_level_0_level_1, allowed_level_0_level_1])

    def _build_ranked_ctes_three_level(
        self,
        table: str,
        where_cte: str,
        ranked_spec: "RankedSubsetSpec",
    ) -> str:
        c0 = self._qcol(ranked_spec.column_level_0)
        c1 = self._qcol(ranked_spec.column_level_1)
        c2 = self._qcol(ranked_spec.column_level_2 or "")
        rcc = self._qcol(ranked_spec.rank_col)
        n0 = int(ranked_spec.top_level_0)
        n1 = int(ranked_spec.top_level_1_per_level_0)
        n2 = int(ranked_spec.top_level_2_per_level_1 or 1)

        cte_where = f"WHERE {where_cte}" if where_cte else ""

        ranked_top_level_0 = (
            f"ranked_top_level_0 AS (\n"
            f"    SELECT l0_inner AS l0 FROM (\n"
            f"        SELECT {c0} AS l0_inner, SUM({rcc}) AS _rs\n"
            f"        FROM {table}\n"
            f"        {cte_where}\n"
            f"        GROUP BY 1\n"
            f"        ORDER BY 2 DESC NULLS LAST\n"
            f"        LIMIT {n0}\n"
            f"    ) AS _sub0\n"
            f")"
        )

        l0_in = f"{c0} IN (SELECT l0 FROM ranked_top_level_0)"
        if where_cte:
            w1 = f"WHERE {where_cte}\n    AND {l0_in}"
        else:
            w1 = f"WHERE {l0_in}"

        agg_level_0_level_1 = (
            f"agg_level_0_level_1 AS (\n"
            f"    SELECT {c0} AS l0, {c1} AS l1, SUM({rcc}) AS _te\n"
            f"    FROM {table}\n"
            f"    {w1}\n"
            f"    GROUP BY 1, 2\n"
            f")"
        )

        allowed_level_0_level_1 = (
            f"allowed_level_0_level_1 AS (\n"
            f"    SELECT l0, l1 FROM (\n"
            f"        SELECT l0, l1, ROW_NUMBER() OVER (PARTITION BY l0 ORDER BY _te DESC NULLS LAST) AS rn\n"
            f"        FROM agg_level_0_level_1\n"
            f"    ) AS _z1\n"
            f"    WHERE rn <= {n1}\n"
            f")"
        )

        exists_01 = (
            f"EXISTS (SELECT 1 FROM allowed_level_0_level_1 AS _x "
            f"WHERE _x.l0 = _rt.{c0} AND _x.l1 = _rt.{c1})"
        )
        if where_cte:
            w2 = f"WHERE {where_cte}\n    AND {exists_01}"
        else:
            w2 = f"WHERE {exists_01}"

        agg_level_0_level_1_level_2 = (
            f"agg_level_0_level_1_level_2 AS (\n"
            f"    SELECT _rt.{c0} AS l0, _rt.{c1} AS l1, _rt.{c2} AS l2, SUM(_rt.{rcc}) AS _tl\n"
            f"    FROM {table} AS _rt\n"
            f"    {w2}\n"
            f"    GROUP BY 1, 2, 3\n"
            f")"
        )

        allowed_level_0_level_1_level_2 = (
            f"allowed_level_0_level_1_level_2 AS (\n"
            f"    SELECT l0, l1, l2 FROM (\n"
            f"        SELECT l0, l1, l2, "
            f"ROW_NUMBER() OVER (PARTITION BY l0, l1 ORDER BY _tl DESC NULLS LAST) AS rn\n"
            f"        FROM agg_level_0_level_1_level_2\n"
            f"    ) AS _z2\n"
            f"    WHERE rn <= {n2}\n"
            f")"
        )

        return ",\n".join(
            [
                ranked_top_level_0,
                agg_level_0_level_1,
                allowed_level_0_level_1,
                agg_level_0_level_1_level_2,
                allowed_level_0_level_1_level_2,
            ]
        )

    def build_ranked_fetch_diagnostic_sqls(
        self,
        date_start: Optional[str],
        date_end: Optional[str],
        filters: Optional[Dict[str, List[str]]],
        ranked_spec: "RankedSubsetSpec",
    ) -> Dict[str, str]:
        """SQL snippets to compare Hyper counts vs pipeline logs (read-only diagnostics).

        For the final aggregated row count, execute :meth:`build_query` and use ``len(df)``.
        Some Hyper builds return inconsistent ``COUNT(*)`` when the subquery contains a
        top-level ``WITH`` clause, so this helper does not emit a wrapped count query.
        """
        agg = self._cfg.aggregation
        if agg is None:
            raise ValueError("build_ranked_fetch_diagnostic_sqls requires aggregation in loader config.")
        table = self._quote_table(self._cfg.hyper.default_table)
        where_kwargs = dict(
            agg=agg,
            date_start=date_start,
            date_end=date_end,
            filters=filters or {},
        )
        where_cte = self._build_where_clause(**where_kwargs, table_alias=None)
        ctes = self._build_ranked_ctes(table, where_cte, ranked_spec)
        c0 = self._qcol(ranked_spec.column_level_0)
        rcc = self._qcol(ranked_spec.rank_col)
        n0 = int(ranked_spec.top_level_0)
        cte_where = f"WHERE {where_cte}" if where_cte else ""

        if where_cte:
            distinct_sql = (
                f"SELECT COUNT(DISTINCT {c0}) AS distinct_level_0_in_range "
                f"FROM {table} WHERE {where_cte}"
            )
        else:
            distinct_sql = f"SELECT COUNT(DISTINCT {c0}) AS distinct_level_0_in_range FROM {table}"

        top_slot_sql = (
            f"SELECT COUNT(*) AS top_level_0_rank_slots_used FROM (\n"
            f"    SELECT {c0} AS l0_inner, SUM({rcc}) AS _rs\n"
            f"    FROM {table}\n"
            f"    {cte_where}\n"
            f"    GROUP BY 1\n"
            f"    ORDER BY 2 DESC NULLS LAST\n"
            f"    LIMIT {n0}\n"
            f") AS _sub0_count"
        )
        if ranked_spec.is_three_level:
            slice_cte = "allowed_level_0_level_1_level_2"
            slice_alias = "allowed_level_0_level_1_level_2"
        else:
            slice_cte = "allowed_level_0_level_1"
            slice_alias = "allowed_level_0_level_1"
        slice_sql = f"WITH\n{ctes}\nSELECT COUNT(*) AS {slice_alias} FROM {slice_cte}"
        return {
            "distinct_level_0_in_range": distinct_sql,
            "top_level_0_rank_slots_used": top_slot_sql,
            slice_alias: slice_sql,
        }

    def _build_ranked_aggregation_sql(
        self,
        agg: AggregationRule,
        table: str,
        where_cte: str,
        where_main: str,
        ranked_spec: "RankedSubsetSpec",
    ) -> str:
        """Full SQL with WITH CTEs, join to allowed ranked slice, then period aggregation."""
        main_where = f"WHERE {where_main}" if where_main else ""
        ctes = self._build_ranked_ctes(table, where_cte, ranked_spec)

        period_expr = self._period_expression(agg, "_f")
        period_alias = self._q(agg.period_alias)
        j0 = self._qualify_alias_col("_f", ranked_spec.column_level_0)
        j1 = self._qualify_alias_col("_f", ranked_spec.column_level_1)
        if ranked_spec.is_three_level:
            j2 = self._qualify_alias_col("_f", ranked_spec.column_level_2 or "")
            join_line = (
                f"INNER JOIN allowed_level_0_level_1_level_2 AS _a ON "
                f"{j0} = _a.l0 AND {j1} = _a.l1 AND {j2} = _a.l2"
            )
        else:
            join_line = (
                f"INNER JOIN allowed_level_0_level_1 AS _a ON {j0} = _a.l0 AND {j1} = _a.l1"
            )

        group_qualified = [self._qualify_alias_col("_f", c) for c in agg.group_by_columns]
        sum_cols_sql = [
            f"SUM({self._qualify_alias_col('_f', c)}) AS \"{c}\"" for c in agg.sum_columns
        ]
        avg_cols_sql = [
            f"AVG({self._qualify_alias_col('_f', c)}) AS \"{c}\"" for c in agg.avg_columns
        ]
        count_distinct_cols_sql = [
            f"COUNT(DISTINCT {self._qualify_alias_col('_f', c)}) AS \"{c}\""
            for c in agg.count_distinct_columns
        ]

        inner_select_parts = (
            [f"{period_expr} AS {period_alias}"]
            + group_qualified
            + sum_cols_sql
            + avg_cols_sql
            + count_distinct_cols_sql
        )
        inner_select = ",\n    ".join(inner_select_parts)
        group_by_parts = [period_expr] + group_qualified
        group_by = ",\n    ".join(group_by_parts)

        body = (
            f"SELECT\n    {inner_select}\n"
            f"FROM {table} AS _f\n"
            f"{join_line}\n"
            f"{main_where}\n"
            f"GROUP BY\n    {group_by}"
        )

        return f"WITH\n{ctes}\n{body}"

    @staticmethod
    def _qualify_alias_col(alias: str, column_name: str) -> str:
        qc = HyperQueryBuilder._qcol(column_name)
        return f"{alias}.{qc}"

    def _build_where_clause(
        self,
        agg: Optional[AggregationRule],
        date_start: Optional[str],
        date_end: Optional[str],
        filters: Dict[str, List[str]],
        table_alias: Optional[str] = None,
    ) -> str:
        """Build a WHERE clause string (without the WHERE keyword).

        Returns an empty string if there are no conditions.
        """
        conditions: List[str] = []

        if agg and (date_start or date_end):
            if agg.date_column:
                dc = self._qualify_table_column(table_alias, self._q(agg.date_column))
                # Filter out extreme dates often used as placeholders (9999-12-31)
                conditions.append(f"{dc} < DATE '2100-01-01'")
                if date_start:
                    conditions.append(f"{dc} >= DATE '{self._esc_val(date_start)}'")
                if date_end:
                    conditions.append(f"{dc} <= DATE '{self._esc_val(date_end)}'")
            elif agg.year_column and agg.month_column:
                # Handle year/month integer filters
                yc = self._qualify_table_column(table_alias, self._q(agg.year_column))
                mc = self._qualify_table_column(table_alias, self._q(agg.month_column))
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
            qc = self._qualify_table_column(table_alias, self._q(col))
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
