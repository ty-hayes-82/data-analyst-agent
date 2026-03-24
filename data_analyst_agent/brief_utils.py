import os
import json
import glob
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class BriefUtils:
    @staticmethod
    def get_latest_cache_dir(base_dir: str = "outputs/ops_metrics_ds") -> Optional[Path]:
        """Find the latest run directory in the specified base directory."""
        search_path = PROJECT_ROOT / base_dir
        if not search_path.exists():
            return None
        
        # Look for run directories (usually timestamped)
        runs = []
        for p in search_path.rglob("202*"):
            if p.is_dir() and any(p.glob("metric_*.json")):
                runs.append(p)
        
        if not runs:
            # Fallback to the tableau-ops_metrics_weekly path if ops_metrics_ds not found
            search_path = PROJECT_ROOT / "outputs/tableau-ops_metrics_weekly/global/all"
            if search_path.exists():
                runs = [p for p in search_path.iterdir() if p.is_dir()]
        
        if not runs:
            return None
            
        return sorted(runs)[-1]

    @staticmethod
    def load_metrics(cache_dir: Path) -> Dict[str, Any]:
        """Load all metric_*.json files from the cache directory."""
        metrics = {}
        for jf in cache_dir.glob("metric_*.json"):
            metric_name = jf.stem.replace("metric_", "")
            try:
                metrics[metric_name] = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"Error loading {jf}: {e}")
        return metrics

    @staticmethod
    def get_network_totals(metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Extract L0 totals for all metrics."""
        totals = {}
        for m, p in metrics.items():
            l0 = p.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
            if l0:
                ev = l0[0].get("evidence", {})
                totals[m] = {
                    "current": ev.get("current", 0),
                    "prior": ev.get("prior", 0),
                    "var_pct": ev.get("variance_pct", 0),
                    "var_dollar": ev.get("variance_dollar", 0)
                }
            else:
                l0_stats = p.get("hierarchical_analysis", {}).get("level_0", {})
                current = l0_stats.get("current_total")
                prior = l0_stats.get("prior_total")
                if current is not None and prior is not None:
                    var = current - prior
                    pct = (var / prior * 100) if prior else 0
                    totals[m] = {
                        "current": current,
                        "prior": prior,
                        "var_pct": pct,
                        "var_dollar": var
                    }
        return totals

class SignalRanker:
    def __init__(self, metrics: Dict[str, Any]):
        self.metrics = metrics
        self.scored_signals: List[Dict[str, Any]] = []

    def _composite_score(self, stat: float, mag: float, mat: float) -> float:
        """Port of priority_engine._composite_score."""
        raw = (stat * 0.5 + mag * 0.3) * (0.4 + 0.6 * mat)
        return round(min(raw, 1.0), 4)

    def _statistical_impact(self, z: float = 0.0, p_value: float = 1.0) -> float:
        z_score = min(abs(z) / 5.0, 1.0)
        p_score = max(1.0 - p_value, 0.0) if p_value < 1.0 else 0.0
        return max(z_score, p_score)

    def _magnitude_impact(self, var_pct: float) -> float:
        # 50% variance is max impact
        return min(abs(var_pct) / 50.0, 1.0)

    def extract_all(self):
        """Pass 0: Unified signal extraction and ranking."""
        self.extract_hierarchy_cards()
        self.extract_trends()
        self.extract_anomalies()
        self.extract_cross_metric()
        self.cluster_by_entity()
        return self.get_ranked_signals()

    def add_signal(self, score: float, category: str, title: str, detail: str, metric: str, source: str, **kwargs):
        # Generate a unique stable ID
        clean_title = re.sub(r'\W+', '_', title).lower()
        signal_id = f"{metric}_{source}_{clean_title}"
        signal = {
            "id": signal_id,
            "score": round(score, 4),
            "category": category,
            "title": title,
            "detail": detail,
            "metric": metric,
            "source": source
        }
        signal.update(kwargs)
        self.scored_signals.append(signal)

    def extract_hierarchy_cards(self):
        """Extract L0-L2 cards from hierarchy analysis."""
        for m, p in self.metrics.items():
            hierarchy = p.get("hierarchical_analysis", {})
            for level_key in ["level_0", "level_1", "level_2"]:
                level = hierarchy.get(level_key, {})
                level_num = int(level_key.split("_")[1])
                for card in level.get("insight_cards", []):
                    ev = card.get("evidence", {})
                    var_pct = ev.get("variance_pct")
                    if var_pct is None: continue
                    
                    item = card.get("title", "").replace(f"Level {level_num} Variance Driver: ", "")
                    
                    stat_impact = 0.5 # Default for hierarchy
                    mag_impact = self._magnitude_impact(var_pct)
                    mat_weight = ev.get("share_of_total", ev.get("materiality_weight", 0.1))
                    
                    # Boost level 0/1
                    level_multiplier = {0: 1.2, 1: 1.1, 2: 1.0}.get(level_num, 1.0)
                    score = self._composite_score(stat_impact, mag_impact, mat_weight) * level_multiplier
                    
                    direction = "+" if var_pct > 0 else ""
                    detail = f"{item}: {m} {direction}{var_pct:.1f}% WoW (${abs(ev.get('variance_dollar', 0)):,.0f})"
                    
                    self.add_signal(score, "Variance", item, detail, m, f"hierarchy_{level_key}", 
                                   entity=item, var_pct=var_pct, share=mat_weight)

    def extract_trends(self):
        """Extract 3-month trends."""
        for m, p in self.metrics.items():
            stats = p.get("statistical_summary", {})
            for driver in stats.get("top_drivers", []):
                slope = driver.get("slope_3mo")
                p_val = driver.get("slope_3mo_p_value")
                avg = driver.get("avg", 0)
                item = driver.get("item", "")
                
                if slope and p_val is not None and p_val < 0.2 and avg:
                    slope_pct = abs(slope / avg * 100)
                    if slope_pct < 0.5: continue
                    
                    stat_impact = self._statistical_impact(p_value=p_val)
                    mag_impact = self._magnitude_impact(slope_pct)
                    mat_weight = 0.5 # Trends are generally important
                    
                    score = self._composite_score(stat_impact, mag_impact, mat_weight) * 0.8
                    
                    direction = "up" if slope > 0 else "down"
                    detail = f"{item}: {m} trending {direction} ~{slope_pct:.1f}%/wk over 13 weeks (p={p_val:.3f})"
                    
                    self.add_signal(score, "Trend", f"{item} {m} trend", detail, m, "statistical_trend",
                                   entity=item, p_value=p_val, slope_pct=slope_pct)

    def extract_anomalies(self):
        """Extract statistical anomalies."""
        for m, p in self.metrics.items():
            stats = p.get("statistical_summary", {})
            period_range = stats.get("summary_stats", {}).get("period_range", "")
            first_period = period_range.split(" to ")[0] if period_range else ""
            
            for anom in stats.get("anomalies", []):
                if anom.get("period") == first_period: continue
                
                z = anom.get("z_score", 0)
                if abs(z) < 2.0: continue
                
                item = anom.get("item_name", anom.get("item", "Total"))
                
                stat_impact = self._statistical_impact(z=z)
                mag_impact = self._magnitude_impact(anom.get("variance_pct", 0))
                mat_weight = 0.4
                
                score = self._composite_score(stat_impact, mag_impact, mat_weight) * 0.9
                
                direction = "spike" if z > 0 else "dip"
                detail = f"{item}: {m} {direction} in {anom.get('period')} (z={z:.1f})"
                
                self.add_signal(score, "Anomaly", f"{item} {m} anomaly", detail, m, "anomaly",
                                   entity=item, z_score=z)

    def extract_cross_metric(self):
        """Compute cross-metric signals from L0 totals."""
        totals = BriefUtils.get_network_totals(self.metrics)
        
        # Yield vs Volume
        rev = totals.get("ttl_rev_xf_sr_amt")
        miles = totals.get("total_miles_rpt")
        if rev and miles:
            rev_pct = rev["var_pct"]
            miles_pct = miles["var_pct"]
            gap = rev_pct - miles_pct
            if abs(gap) > 1.0:
                score = abs(gap) * 0.05
                if rev_pct < miles_pct:
                    detail = f"Yield compressing: Revenue {rev_pct:+.1f}% vs Miles {miles_pct:+.1f}% (gap {gap:+.1f}pts)"
                else:
                    detail = f"Yield improving: Revenue {rev_pct:+.1f}% vs Miles {miles_pct:+.1f}% (gap {gap:+.1f}pts)"
                self.add_signal(score, "Yield", "Yield vs Volume", detail, "cross_metric", "cross_metric")

        # Deadhead vs Miles
        dh = totals.get("deadhead_pct")
        if dh:
            dh_var = dh["var_pct"] # This is usually point change for a percentage metric
            if abs(dh_var) > 0.5:
                score = abs(dh_var) * 0.2
                direction = "deteriorating" if dh_var > 0 else "improving"
                detail = f"Network efficiency {direction}: Deadhead {dh_var:+.2f}pts WoW"
                self.add_signal(score, "Efficiency", "DH trend", detail, "deadhead_pct", "cross_metric")

    def cluster_by_entity(self):
        """Group L2 cards by entity across metrics."""
        clusters = defaultdict(list)
        for s in self.scored_signals:
            if s.get("source") == "hierarchy_level_2" and s.get("entity"):
                clusters[s["entity"]].append(s)
        
        for entity, signals in clusters.items():
            if len(signals) > 1:
                # Build a composite signal
                combined_detail = f"{entity} multi-metric move: " + "; ".join([f"{s['metric']} {s['var_pct']:+.1f}%" for s in signals])
                avg_score = sum(s["score"] for s in signals) / len(signals)
                bonus = 0.1 * (len(signals) - 1)
                new_score = min(avg_score + bonus, 1.0)
                
                self.add_signal(new_score, "Entity Cluster", f"{entity} composite", combined_detail, "multi", "cluster",
                               entity=entity, sub_signals=[s["detail"] for s in signals])

    def get_ranked_signals(self, top_n: int = 30) -> List[Dict[str, Any]]:
        # Deduplicate by (title, metric, source)
        seen = set()
        deduped = []
        for s in sorted(self.scored_signals, key=lambda x: x["score"], reverse=True):
            key = (s["title"], s["metric"], s["source"])
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        return deduped[:top_n]

def pass1_curate(client, model: str, totals: Dict[str, Any], signals: List[Dict[str, Any]], max_curated: int) -> Dict[str, Any]:
    """Pass 1: Flash-Lite selects the most important signals from the ranked pool."""
    from google.genai import types
    import time
    
    # Filter signals for input: keep only id, category, detail, score
    input_signals = []
    for s in signals:
        input_signals.append({
            "id": s["id"],
            "category": s["category"],
            "detail": s["detail"],
            "score": s["score"]
        })
    
    prompt = (
        "You are a senior analyst for a trucking company. You have a list of ranked operational signals (deterministic stats).\n"
        f"Your job is to select the TOP {max_curated} most impactful and coherent signals for an executive CEO brief.\n"
        "DROP signals that are noise, contradictory, or redundant across metrics.\n"
        "ENSURE coverage across Revenue, Efficiency, and Capacity if significant moves exist.\n\n"
        "NETWORK TOTALS (for context):\n"
    )
    for m, d in totals.items():
        prompt += f"- {m}: {d['var_pct']:+.1f}% WoW (${abs(d['var_dollar']):,.0f})\n"
    
    prompt += "\nRANKED SIGNALS (from Pass 0):\n"
    prompt += json.dumps(input_signals, indent=2)
    
    schema = types.Schema(type=types.Type.OBJECT, properties={
        "kept": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
            "id": types.Schema(type=types.Type.STRING),
            "rank": types.Schema(type=types.Type.INTEGER),
            "one_line_why": types.Schema(type=types.Type.STRING)
        }, required=["id", "rank", "one_line_why"])),
        "dropped": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
            "id": types.Schema(type=types.Type.STRING),
            "reason": types.Schema(type=types.Type.STRING)
        }, required=["id", "reason"])),
        "narrative_thesis": types.Schema(type=types.Type.STRING, description="A single sentence summarizing the week's performance.")
    }, required=["kept", "dropped", "narrative_thesis"])

    t0 = time.time()
    r = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction="You are a data curation agent. Output strictly JSON.",
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.1
        )
    )
    el = time.time() - t0
    curation = json.loads(r.text)
    curation["_elapsed"] = el
    return curation

def pass2_brief(client, model: str, totals: Dict[str, Any], signals: List[Dict[str, Any]], thesis: str, period: str) -> Dict[str, Any]:
    """Pass 2: Synthesize final CEO brief from curated signals."""
    from google.genai import types
    import time
    
    prompt_template = (PROJECT_ROOT / "config/prompts/executive_brief_ceo.md").read_text(encoding="utf-8").strip()
    system_instruction = prompt_template.replace("{analysis_period}", period)
    # Clear other template vars
    for k in ["metric_count", "scope_preamble", "dataset_specific_append", "prompt_variant_append"]:
        system_instruction = system_instruction.replace("{" + k + "}", "")
    
    user_msg = (
        f"ANALYSIS PERIOD: {period}. All variances are WoW.\n"
        f"WEEKLY THESIS: {thesis}\n\n"
        "NETWORK TOTALS:\n"
    )
    for m, d in totals.items():
        user_msg += f"- {m}: {d['var_pct']:+.1f}% WoW (${abs(d['var_dollar']):,.0f}), current ${d['current']:,.0f}\n"
    
    user_msg += "\nCURATED INSIGHTS (use ONLY these signals, preserve exact numbers):\n"
    for i, s in enumerate(signals, 1):
        user_msg += f"{i}. [{s['category']}] {s['detail']}\n"

    user_msg += (
        "\nGROUNDING (mandatory):\n"
        "- Every numeric claim must come verbatim from NETWORK TOTALS or CURATED INSIGHTS above. "
        "Do not invent revenue bands, dollar outlook ranges, or scenario numbers.\n"
        "- Never mirror the same percentage across two different metrics (e.g. deadhead change in pts "
        "vs LRPM in $/mi). State the unit explicitly for each figure (pts, % WoW, $, etc.).\n"
        "- next_week_outlook: qualitative or mechanism-only unless a specific number appears in the "
        "signals above; do not add best/worst-case dollar ranges.\n"
    )

    schema = types.Schema(type=types.Type.OBJECT, properties={
        "bottom_line": types.Schema(type=types.Type.STRING),
        "what_moved": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
            "label": types.Schema(type=types.Type.STRING),
            "line": types.Schema(type=types.Type.STRING),
        }, required=["label", "line"])),
        "trend_status": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "where_it_came_from": types.Schema(type=types.Type.OBJECT, properties={
            "positive": types.Schema(type=types.Type.STRING),
            "drag": types.Schema(type=types.Type.STRING),
            "watch_item": types.Schema(type=types.Type.STRING),
        }, required=["positive", "drag"]),
        "why_it_matters": types.Schema(type=types.Type.STRING),
        "next_week_outlook": types.Schema(type=types.Type.STRING),
        "leadership_focus": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
    }, required=["bottom_line", "what_moved", "trend_status", "where_it_came_from",
                 "why_it_matters", "next_week_outlook", "leadership_focus"])

    t0 = time.time()
    r = client.models.generate_content(
        model=model,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2
        )
    )
    el = time.time() - t0
    brief = json.loads(r.text)
    brief["_elapsed"] = el
    return brief
