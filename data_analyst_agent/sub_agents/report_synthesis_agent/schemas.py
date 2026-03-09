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
# WITHOUT WARRANTIES OR CONDITIONS OF KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Canonical JSON schemas for generate_markdown_report tool inputs.

These schemas document the expected structure for the report synthesis agent.
The tool accepts and normalizes multiple formats; these define the preferred
(canonical) format for consistency.
"""

# Canonical hierarchical_results structure
# Top-level: dict with level_0, level_1, (level_2) keys
# Each level: dict with insight_cards, total_variance_dollar, level_name
INSIGHT_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "what_changed": {"type": "string"},
        "why": {"type": "string"},
        "evidence": {"type": "object"},
        "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "impact_score": {"type": "number"},
    },
}

HIERARCHICAL_RESULTS_SCHEMA = {
    "type": "object",
    "properties": {
        "level_0": {
            "type": "object",
            "properties": {
                "insight_cards": {"type": "array", "items": INSIGHT_CARD_SCHEMA},
                "total_variance_dollar": {"type": "number"},
                "level_name": {"type": "string"},
            },
        },
        "level_1": {
            "type": "object",
            "properties": {
                "insight_cards": {"type": "array", "items": INSIGHT_CARD_SCHEMA},
                "total_variance_dollar": {"type": "number"},
                "level_name": {"type": "string"},
            },
        },
        "level_2": {
            "type": "object",
            "properties": {
                "insight_cards": {"type": "array", "items": INSIGHT_CARD_SCHEMA},
                "total_variance_dollar": {"type": "number"},
                "level_name": {"type": "string"},
            },
        },
    },
}

# Canonical narrative_results structure
NARRATIVE_RESULTS_SCHEMA = {
    "type": "object",
    "properties": {
        "insight_cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "what_changed": {"type": "string"},
                    "why": {"type": "string"},
                    "evidence": {"type": ["object", "string"]},
                    "priority": {"type": "string"},
                    "root_cause": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "narrative_summary": {"type": "string"},
    },
}

# Canonical statistical_summary (slim subset for synthesis)
STATISTICAL_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_stats": {
            "type": "object",
            "properties": {
                "total_items": {"type": "integer"},
                "total_periods": {"type": "integer"},
                "period_range": {"type": "string"},
                "highest_total_month": {"type": "object", "properties": {"period": {"type": "string"}, "total": {"type": "number"}}},
                "lowest_total_month": {"type": "object", "properties": {"period": {"type": "string"}, "total": {"type": "number"}}},
                "total_anomalies_detected": {"type": "integer"},
            },
        },
        "top_drivers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "avg": {"type": "number"},
                    "slope_3mo": {"type": "number"},
                    "share_of_total": {"type": "number"},
                    "anomaly_latest": {"type": "boolean"},
                    "z_score": {"type": "number"},
                },
            },
        },
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "item": {"type": "string"},
                    "value": {"type": "number"},
                    "z_score": {"type": "number"},
                },
            },
        },
    },
}
