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

"""Generate executive summary using 3-level drill-down format."""

import json
from google.genai.types import Tool, FunctionDeclaration


def generate_executive_summary_func(
    category_analysis: str,
    gl_drilldown: str,
    variance_summary: str,
    materiality_flags: str = "{}"
) -> str:
    """
    Generates a 3-level executive summary in the standard format.
    
    Level 1: High-level summary (5 bullets)
    - Overall variance vs baselines (YoY, MoM, 3MMA, 6MMA)
    - Top 2-4 category drivers
    - Seasonal/timing factors
    - Next steps
    
    Level 2: Category analysis
    - Top categories ranked by dollar impact
    - Cumulative variance explained
    
    Level 3: GL drill-down
    - Individual GLs within top categories
    - Root cause classification
    - One-time vs run-rate
    
    Args:
        category_analysis: JSON string from category_analyzer_agent
        gl_drilldown: JSON string from gl_drilldown_agent
        variance_summary: JSON string with overall variance metrics
        materiality_flags: JSON string with materiality thresholds
        
    Returns:
        JSON string with structured 3-level summary
    """
    try:
        # Parse inputs
        categories = json.loads(category_analysis) if category_analysis else {}
        gl_analysis = json.loads(gl_drilldown) if gl_drilldown else {}
        variances = json.loads(variance_summary) if variance_summary else {}
        material = json.loads(materiality_flags) if materiality_flags else {}
        
        # Extract key metrics
        top_categories = categories.get("top_drivers", [])[:4]
        total_variance = variances.get("total_dollar_variance", 0)
        yoy_pct = variances.get("yoy_variance_pct", 0)
        mom_pct = variances.get("mom_variance_pct", 0)
        ma3_pct = variances.get("ma3_variance_pct", 0)
        ma6_pct = variances.get("ma6_variance_pct", 0)
        
        # Level 1: Executive Summary (5 bullets)
        level_1_bullets = []
        
        # Bullet 1: Overall variance
        level_1_bullets.append(
            f"Total variance: ${total_variance:,.0f} ({yoy_pct:+.1f}% YoY, {mom_pct:+.1f}% MoM)"
        )
        
        # Bullet 2: Baseline comparisons
        level_1_bullets.append(
            f"vs. Baselines: 3-month avg {ma3_pct:+.1f}%, 6-month avg {ma6_pct:+.1f}%"
        )
        
        # Bullet 3-4: Top category drivers
        for i, cat in enumerate(top_categories[:2]):
            cat_name = cat.get("category", "Unknown")
            cat_var = cat.get("dollar_variance", 0)
            cat_pct = cat.get("cumulative_pct", 0)
            level_1_bullets.append(
                f"{cat_name}: ${cat_var:,.0f} ({cat_pct:.0f}% of total)"
            )
        
        # Bullet 5: Next steps
        if len(top_categories) > 0:
            level_1_bullets.append(
                f"Focus areas: {', '.join([c.get('category', '') for c in top_categories[:3]])}"
            )
        
        # Level 2: Category Analysis
        level_2_categories = [
            {
                "rank": i + 1,
                "category": cat.get("category", ""),
                "dollar_variance": cat.get("dollar_variance", 0),
                "percent_variance": cat.get("percent_variance", 0),
                "cumulative_pct": cat.get("cumulative_pct", 0),
                "is_material": cat.get("is_material", False)
            }
            for i, cat in enumerate(top_categories)
        ]
        
        # Level 3: GL Drill-Down
        level_3_gls = gl_analysis.get("gl_details", [])
        
        # Questions for cost center manager
        questions = []
        for cat in top_categories[:3]:
            cat_name = cat.get("category", "")
            questions.append(f"What operational changes drove the {cat_name} variance?")
        
        # Build final summary
        summary = {
            "report_type": "3_level_executive_summary",
            "level_1_summary": {
                "bullets": level_1_bullets[:5],  # Max 5 bullets
                "total_variance": total_variance,
                "baseline_comparisons": {
                    "yoy_pct": yoy_pct,
                    "mom_pct": mom_pct,
                    "ma3_pct": ma3_pct,
                    "ma6_pct": ma6_pct
                }
            },
            "level_2_category_analysis": {
                "top_drivers": level_2_categories,
                "categories_analyzed": len(top_categories)
            },
            "level_3_gl_drilldown": {
                "gl_details": level_3_gls,
                "gls_analyzed": len(level_3_gls)
            },
            "questions_for_manager": questions,
            "materiality_thresholds": material
        }
        
        return json.dumps(summary, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": f"Failed to generate executive summary: {str(e)}",
            "report_type": "3_level_executive_summary"
        })


# Tool declaration for Google GenAI
generate_executive_summary = Tool(
    function_declarations=[
        FunctionDeclaration(
            name="generate_executive_summary",
            description="Generates a 3-level executive summary (Level 1: bullets, Level 2: categories, Level 3: GL drill-down)",
            parameters={
                "type": "object",
                "properties": {
                    "category_analysis": {
                        "type": "string",
                        "description": "JSON string from category_analyzer_agent"
                    },
                    "gl_drilldown": {
                        "type": "string",
                        "description": "JSON string from gl_drilldown_agent"
                    },
                    "variance_summary": {
                        "type": "string",
                        "description": "JSON string with overall variance metrics"
                    },
                    "materiality_flags": {
                        "type": "string",
                        "description": "JSON string with materiality thresholds"
                    }
                },
                "required": ["category_analysis", "gl_drilldown", "variance_summary"]
            }
        )
    ]
)


def _call_function(func_name: str, args: dict) -> str:
    """Helper to call the function."""
    if func_name == "generate_executive_summary":
        return generate_executive_summary_func(**args)
    raise ValueError(f"Unknown function: {func_name}")

