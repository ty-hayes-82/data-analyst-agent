"""Utilities for normalizing Agent-to-Agent (A2A) responses into CSV."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd


@dataclass
class _TimeSpec:
    column: Optional[str] = None
    format: Optional[str] = None


class A2aResponseNormalizer:
    """Normalizes heterogeneous A2A payloads to CSV strings."""

    def __init__(self, contract: Any):
        self.contract = contract

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def normalize_response(self, raw_response: Optional[str]) -> str:
        """Normalize arbitrary payloads (JSON / CSV / markdown) to CSV."""
        cleaned = self._clean_raw(raw_response)
        if not cleaned:
            return ""

        parsed = self._try_parse_json(cleaned)
        df: Optional[pd.DataFrame] = None

        if isinstance(parsed, dict):
            if "data" in parsed:
                df = self._normalize_data_payload(parsed["data"])
            elif "time_series" in parsed:
                df = self._records_to_dataframe(parsed["time_series"])
        elif isinstance(parsed, list):
            df = self._records_to_dataframe(parsed)

        if df is None:
            df = self._dataframe_from_csv(cleaned)

        if df is None or df.empty and not df.columns.any():
            return ""

        df = self._post_process_dataframe(df)
        return df.to_csv(index=False)

    @staticmethod
    def extract_time_series(payload: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        """Extract time_series array from JSON payload."""
        if payload is None:
            return None

        try:
            parsed = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return None

        if isinstance(parsed, dict):
            ts = parsed.get("time_series")
            if isinstance(ts, list):
                return ts
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _clean_raw(self, raw: Optional[str]) -> str:
        if raw is None:
            return ""
        text = str(raw).strip()
        if not text:
            return ""
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            # Drop first/last fences
            if len(lines) >= 2:
                lines = lines[1:-1]
            text = "\n".join(lines).strip()
        return text

    def _try_parse_json(self, candidate: str) -> Optional[Any]:
        try:
            return json.loads(candidate)
        except Exception:
            return None

    def _normalize_data_payload(self, data_field: Any) -> Optional[pd.DataFrame]:
        if data_field is None:
            return None
        if isinstance(data_field, str):
            return self._dataframe_from_csv(data_field)
        if isinstance(data_field, list):
            return self._records_to_dataframe(data_field)
        if isinstance(data_field, dict):
            return self._columnar_to_dataframe(data_field)
        return None

    def _records_to_dataframe(self, records: Sequence[Dict[str, Any]]) -> Optional[pd.DataFrame]:
        if not records:
            return None
        try:
            return pd.DataFrame(list(records))
        except Exception:
            return None

    def _columnar_to_dataframe(self, columns: Dict[str, Sequence[Any]]) -> Optional[pd.DataFrame]:
        if not columns:
            return None
        try:
            return pd.DataFrame(columns)
        except Exception:
            return None

    def _dataframe_from_csv(self, csv_text: str) -> Optional[pd.DataFrame]:
        try:
            return pd.read_csv(StringIO(csv_text))
        except Exception:
            return None

    def _post_process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if "sign_flipped" not in df.columns:
            df["sign_flipped"] = False
        else:
            df["sign_flipped"] = df["sign_flipped"].astype(bool, copy=False)

        self._remap_period_end(df)
        return df

    # ------------------------------------------------------------------
    # Period remapping helpers
    # ------------------------------------------------------------------
    def _remap_period_end(self, df: pd.DataFrame) -> None:
        time_spec = self._get_time_spec()
        if not time_spec.column:
            return

        source_col = "period_end_date"
        target_col = time_spec.column
        if source_col not in df.columns:
            if target_col == source_col and source_col in df.columns:
                self._apply_time_format(df, target_col, time_spec.format)
            return

        if target_col == source_col:
            self._apply_time_format(df, target_col, time_spec.format)
            return

        df[target_col] = df[source_col].apply(lambda value: self._format_period_value(value, time_spec.format))
        df.drop(columns=[source_col], inplace=True)

    def _apply_time_format(self, df: pd.DataFrame, column: str, fmt: Optional[str]) -> None:
        if not fmt or column not in df.columns:
            return
        df[column] = df[column].apply(lambda value: self._format_period_value(value, fmt))

    def _format_period_value(self, value: Any, target_fmt: Optional[str]) -> Any:
        if not target_fmt or value is None:
            return value
        text = str(value).strip()
        if not text:
            return value

        input_formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m", "%Y%m%d"]
        for in_fmt in input_formats:
            try:
                parsed = datetime.strptime(text, in_fmt)
                return parsed.strftime(target_fmt)
            except ValueError:
                continue
        if target_fmt == "%Y-%m" and len(text) >= 7:
            return text[:7]
        return text

    def _get_time_spec(self) -> _TimeSpec:
        time_attr = getattr(self.contract, "time", None)
        if not time_attr:
            return _TimeSpec()
        column = getattr(time_attr, "column", None)
        fmt = getattr(time_attr, "format", None)
        return _TimeSpec(column=column, format=fmt)
