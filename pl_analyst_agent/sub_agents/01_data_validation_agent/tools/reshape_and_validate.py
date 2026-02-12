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

"""
Reshape And Validate tool for ingest_validator_agent.
"""

import json
from typing import Any, Dict, List, Tuple
from datetime import datetime


def _reshape_row(row: Dict[str, Any], id_fields: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """
    Reshape a wide-format row into multiple time-series records.
    
    Args:
        row: Dictionary with id_fields and period columns
        id_fields: Tuple of field names to preserve as identifiers
    
    Returns:
        List of time-series dictionaries
    """
    out = []
    id_vals = {k: row[k] for k in id_fields if k in row}
    for col_name, val in row.items():
        if col_name not in id_fields:
            rec = {"period": col_name, "amount": val}
            rec.update(id_vals)
            out.append(rec)
    return out


def _filter_invalid_periods(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Filter out periods with invalid months (< 1 or > 12).
    
    Args:
        series: List of time-series records with 'period' field
    
    Returns:
        Dictionary with 'valid_series' and 'invalid_periods' keys
    """
    valid_series = []
    invalid_periods = []
    
    for record in series:
        period = record.get("period", "")
        try:
            year, month = period.split("-")
            month_int = int(month)
            if 1 <= month_int <= 12:
                valid_series.append(record)
            else:
                invalid_periods.append(period)
        except (ValueError, AttributeError):
            invalid_periods.append(period)
    
    return {"valid_series": valid_series, "invalid_periods": invalid_periods}


def _validate_series(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate time series data for gaps and back-dated postings.
    
    Args:
        series: List of time-series records sorted by period
    
    Returns:
        Dictionary with quality flags
    """
    flags = {"missing_months": [], "back_dated_postings": False, "non_numeric_amounts": False}
    if not series:
        return flags

    def parse(period: str) -> datetime:
        return datetime.strptime(period, "%Y-%m")

    for idx in range(1, len(series)):
        prev = parse(series[idx - 1]["period"])
        cur = parse(series[idx]["period"])
        gap = (cur.year - prev.year) * 12 + (cur.month - prev.month)
        if gap > 1:
            flags["missing_months"].append(f"gap_before_{series[idx]['period']}")
        if gap < 0:
            flags["back_dated_postings"] = True

    return flags


async def reshape_and_validate(data: str) -> str:
    """
    Input JSON formats supported:
      - {"rows": [ {wide row dicts} ], "id_fields": [..] }
      - {"time_series": [{"period":"YYYY-MM","amount":...}], ...}

    Returns: {
      "analysis_type": "ingest_validation",
      "time_series": [...],
      "quality_flags": {...}
    }
    """
    try:
        # Strip markdown code fences if present
        data_clean = data.strip()
        if data_clean.startswith("```json"):
            data_clean = data_clean[7:]  # Remove ```json
        elif data_clean.startswith("```"):
            data_clean = data_clean[3:]   # Remove ```
        if data_clean.endswith("```"):
            data_clean = data_clean[:-3]  # Remove closing ```
        data_clean = data_clean.strip()
        
        # Try to extract just the JSON object if there's extra text
        # Find the first { and last }
        start_idx = data_clean.find('{')
        end_idx = data_clean.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            data_clean = data_clean[start_idx:end_idx+1]
        
        payload = json.loads(data_clean)
        id_fields: Tuple[str, ...] = tuple(payload.get("id_fields", ["gl_cst_ctr_cd"])
        )

        if "time_series" in payload:
            series = payload["time_series"]
            if not isinstance(series, list):
                return json.dumps({
                    "error": "DataUnavailable",
                    "source": "ingest_validator",
                    "detail": "time_series must be a list",
                    "action": "stop",
                })
        else:
            rows = payload.get("rows", [])
            if not rows:
                return json.dumps({
                    "error": "DataUnavailable",
                    "source": "ingest_validator",
                    "detail": "No rows provided",
                    "action": "stop",
                })
            series = []
            for row in rows:
                series.extend(_reshape_row(row, id_fields))

        if not series or not all(("period" in r and "amount" in r) for r in series):
            return json.dumps({
                "error": "DataUnavailable",
                "source": "ingest_validator",
                "detail": "Each record must include 'period' and 'amount'",
                "action": "stop",
            })

        # Filter out invalid periods (e.g., 2024-14, fiscal period adjustments) before validation
        # Note: Periods with month > 12 or < 1 are automatically excluded
        filter_result = _filter_invalid_periods(series)
        cleaned_series = filter_result["valid_series"]
        invalid_periods = filter_result["invalid_periods"]
        
        if not cleaned_series:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "ingest_validator",
                "detail": f"All periods invalid. Filtered: {invalid_periods}",
                "action": "stop",
            })

        flags = _validate_series(cleaned_series)
        
        # Add filtered periods to quality flags with clear messaging
        if invalid_periods:
            flags["filtered_invalid_periods"] = invalid_periods
            flags["records_filtered"] = len(invalid_periods)
            flags["records_retained"] = len(cleaned_series)
            flags["filter_reason"] = "Periods with month > 12 or < 1 (fiscal adjustments, period 13/14) automatically excluded"
            print(f"[ingest_validator]: Filtered {len(invalid_periods)} invalid period(s): {invalid_periods}")
        
        return json.dumps({
            "analysis_type": "ingest_validation",
            "time_series": cleaned_series,
            "quality_flags": flags,
        }, indent=2)

    except Exception as e:
        return json.dumps({
            "error": "ProcessingError",
            "source": "ingest_validator",
            "detail": str(e),
            "action": "stop",
        })
