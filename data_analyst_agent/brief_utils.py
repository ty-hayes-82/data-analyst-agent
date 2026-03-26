import os
import json
import glob
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def format_brief_current_value(current: Any) -> str:
    """Format level-0 / network current values for CEO brief prompts.

    Large revenue totals use whole dollars; small per-mile or per-unit rates keep decimals.
    """
    if current is None:
        return "N/A"
    try:
        f = float(current)
    except (TypeError, ValueError):
        return str(current)
    a = abs(f)
    if a < 100:
        return f"${f:,.2f}"
    if a < 10_000:
        return f"${f:,.1f}"
    return f"${f:,.0f}"


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    """JSON-null or non-dict nested fields must not break chained .get() calls."""
    return value if isinstance(value, dict) else {}


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
            if p.is_dir():
                # Check new layout: metrics/metric_*.json
                if any((p / "metrics").glob("metric_*.json")):
                    runs.append(p)
                # Check legacy layout: metric_*.json at root
                elif any(p.glob("metric_*.json")):
                    runs.append(p)
        
        if not runs:
            # Fallback to the tableau-ops_metrics_weekly path if ops_metrics_ds not found
            # (Checks both layouts there too)
            search_path = PROJECT_ROOT / "outputs/tableau-ops_metrics_weekly/global/all"
            if search_path.exists():
                for p in search_path.iterdir():
                    if p.is_dir():
                        if any((p / "metrics").glob("metric_*.json")) or any(p.glob("metric_*.json")):
                            runs.append(p)
        
        if not runs:
            return None
            
        return sorted(runs)[-1]

    @staticmethod
    def load_metrics(cache_dir: Path) -> Dict[str, Any]:
        """Load all metric_*.json files from the cache directory (checks both layouts)."""
        metrics = {}
        
        # Check new layout first
        metrics_dir = cache_dir / "metrics"
        search_dirs = [metrics_dir, cache_dir] if metrics_dir.exists() else [cache_dir]
        
        processed_stems = set()
        for s_dir in search_dirs:
            for jf in s_dir.glob("metric_*.json"):
                if jf.stem in processed_stems:
                    continue
                metric_name = jf.stem.replace("metric_", "")
                try:
                    metrics[metric_name] = json.loads(jf.read_text(encoding="utf-8"))
                    processed_stems.add(jf.stem)
                except Exception as e:
                    print(f"Error loading {jf}: {e}")
        return metrics

    @staticmethod
    def get_network_totals(metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Extract L0 totals for all metrics."""
        totals = {}
        for m, p in metrics.items():
            ha = _dict_or_empty(p.get("hierarchical_analysis"))
            l0_block = _dict_or_empty(ha.get("level_0"))
            l0 = l0_block.get("insight_cards") or []
            if not isinstance(l0, list):
                l0 = []
            if l0:
                ev = l0[0].get("evidence", {}) if isinstance(l0[0], dict) else {}
                totals[m] = {
                    "current": ev.get("current", 0),
                    "prior": ev.get("prior", 0),
                    "var_pct": ev.get("variance_pct", 0),
                    "var_dollar": ev.get("variance_dollar", 0)
                }
            else:
                l0_stats = l0_block
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
        self.extract_temporal_benchmarks()
        self.extract_concentration_risk()
        self.extract_price_volume_decomposition()
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
            hierarchy = _dict_or_empty(p.get("hierarchical_analysis"))
            for level_key in ["level_0", "level_1", "level_2"]:
                level = _dict_or_empty(hierarchy.get(level_key))
                level_num = int(level_key.split("_")[1])
                cards = level.get("insight_cards") or []
                if not isinstance(cards, list):
                    cards = []
                for card in cards:
                    if not isinstance(card, dict):
                        continue
                    raw_ev = card.get("evidence")
                    ev = raw_ev if isinstance(raw_ev, dict) else {}
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
                    if ev.get("current") is not None:
                        detail += f", current {format_brief_current_value(ev.get('current'))}"

                    h_kwargs: Dict[str, Any] = {
                        "entity": item,
                        "var_pct": var_pct,
                        "share": mat_weight,
                    }
                    if ev.get("current") is not None:
                        h_kwargs["current_value"] = ev.get("current")
                    if ev.get("prior") is not None:
                        h_kwargs["prior_value"] = ev.get("prior")

                    self.add_signal(
                        score,
                        "Variance",
                        item,
                        detail,
                        m,
                        f"hierarchy_{level_key}",
                        **h_kwargs,
                    )

    def extract_trends(self):
        """Extract 3-month trends."""
        for m, p in self.metrics.items():
            stats = _dict_or_empty(p.get("statistical_summary"))
            drivers = stats.get("top_drivers") or []
            if not isinstance(drivers, list):
                drivers = []
            for driver in drivers:
                if not isinstance(driver, dict):
                    continue
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
            stats = _dict_or_empty(p.get("statistical_summary"))
            period_range = _dict_or_empty(stats.get("summary_stats")).get("period_range", "")
            first_period = period_range.split(" to ")[0] if period_range else ""
            anomalies = stats.get("anomalies") or []
            if not isinstance(anomalies, list):
                anomalies = []
            for anom in anomalies:
                if not isinstance(anom, dict):
                    continue
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
        """Compute cross-metric signals from L0 totals — generic, contract-driven.

        Detects three patterns across any combination of metrics:
        1. Divergence: metric A up, metric B down (e.g., sales up but profit down)
        2. Rate mismatch: both move same direction but at very different rates
        """
        totals = BriefUtils.get_network_totals(self.metrics)
        if not totals:
            return

        # Collect all metrics with valid variance data
        metric_vars = []
        for name, data in totals.items():
            if isinstance(data, dict) and "var_pct" in data and data["var_pct"] is not None:
                try:
                    var_pct = float(data["var_pct"])
                    display = data.get("display_name", name)
                    metric_vars.append({"name": name, "display": display, "var_pct": var_pct})
                except (ValueError, TypeError):
                    continue

        if len(metric_vars) < 2:
            return

        # Check all pairs for divergence and rate mismatch
        for i in range(len(metric_vars)):
            for j in range(i + 1, len(metric_vars)):
                a = metric_vars[i]
                b = metric_vars[j]
                a_pct = a["var_pct"]
                b_pct = b["var_pct"]

                # Pattern 1: Divergence (opposite directions, both material)
                if a_pct * b_pct < 0 and abs(a_pct) > 2.0 and abs(b_pct) > 2.0:
                    gap = abs(a_pct - b_pct)
                    score = min(gap * 0.03, 1.0)
                    up_metric = a if a_pct > 0 else b
                    down_metric = b if a_pct > 0 else a
                    detail = (
                        f"Divergence: {up_metric['display']} {up_metric['var_pct']:+.1f}% "
                        f"vs {down_metric['display']} {down_metric['var_pct']:+.1f}% "
                        f"(gap {gap:.1f}pts) — {up_metric['display']} growth may be low-quality"
                    )
                    self.add_signal(score, "Cross-Metric", f"{a['display']} vs {b['display']}",
                                   detail, "cross_metric", "cross_metric")

                # Pattern 2: Rate mismatch (same direction, different magnitudes)
                elif a_pct * b_pct > 0 and abs(a_pct) > 3.0 and abs(b_pct) > 3.0:
                    ratio = max(abs(a_pct), abs(b_pct)) / max(min(abs(a_pct), abs(b_pct)), 0.1)
                    if ratio > 2.0:
                        score = min((ratio - 2.0) * 0.1, 0.8)
                        faster = a if abs(a_pct) > abs(b_pct) else b
                        slower = b if abs(a_pct) > abs(b_pct) else a
                        detail = (
                            f"Rate mismatch: {faster['display']} moving {abs(faster['var_pct']):.1f}% "
                            f"vs {slower['display']} {abs(slower['var_pct']):.1f}% "
                            f"({ratio:.1f}x faster) — investigate mix shift or pricing change"
                        )
                        self.add_signal(score, "Cross-Metric", f"{a['display']} rate gap",
                                       detail, "cross_metric", "cross_metric")


    def extract_temporal_benchmarks(self):
        """Add temporal context: 'worst since X', 'above N-period average'."""
        for m, payload in self.metrics.items():
            stats = _dict_or_empty(payload.get("statistical_summary"))
            summary = _dict_or_empty(stats.get("summary_stats"))
            totals = BriefUtils.get_network_totals({m: payload})
            m_total = totals.get(m, {})
            current = m_total.get("current", 0)
            var_pct = m_total.get("var_pct", 0)

            # Check if current is near historical extremes
            highest = summary.get("highest_total_period", {})
            lowest = summary.get("lowest_total_period", {})

            if highest and current and highest.get("total"):
                pct_of_high = current / highest["total"] * 100
                if pct_of_high >= 90:
                    detail = f"{m} at {pct_of_high:.0f}% of all-time high ({highest.get('period', '?')})"
                    self.add_signal(0.3, "Temporal", f"{m} near high", detail, m, "temporal_benchmark")

            if lowest and current and lowest.get("total") and lowest["total"] > 0:
                pct_of_low = current / lowest["total"] * 100
                if pct_of_low <= 150:
                    detail = f"{m} within 50% of all-time low ({lowest.get('period', '?')})"
                    self.add_signal(0.4, "Temporal", f"{m} near low", detail, m, "temporal_benchmark")

            # Check vs top driver averages (rolling context)
            top_drivers = stats.get("top_drivers", [])
            if top_drivers and isinstance(top_drivers, list):
                for driver in top_drivers[:3]:
                    avg = driver.get("avg", 0)
                    item = driver.get("item_name", driver.get("item", ""))
                    slope = driver.get("slope_3mo", 0)
                    if avg and item and slope:
                        if abs(slope) > avg * 0.1:  # slope > 10% of average = meaningful trend
                            direction = "accelerating" if slope > 0 else "decelerating"
                            detail = f"{item} {m} is {direction} (3-mo slope {slope:+.1f} vs avg {avg:.1f})"
                            self.add_signal(0.25, "Trend Momentum", f"{item} {direction}", detail, m, "temporal_benchmark")

    def extract_concentration_risk(self):
        """Flag when a few entities dominate total volume — concentration risk."""
        for m, payload in self.metrics.items():
            ha = _dict_or_empty(payload.get("hierarchical_analysis"))
            for level_key in ["level_1", "level_2"]:
                level = _dict_or_empty(ha.get(level_key))
                cards = level.get("insight_cards", [])
                if not cards or len(cards) < 3:
                    continue

                # Calculate concentration from share_current
                shares = []
                for card in cards:
                    ev = card.get("evidence", {}) if isinstance(card.get("evidence"), dict) else {}
                    share = ev.get("share_current") or ev.get("share_of_total")
                    entity = ev.get("entity", card.get("title", ""))
                    if share is not None:
                        shares.append((entity, float(share)))

                if len(shares) < 3:
                    continue

                shares.sort(key=lambda x: x[1], reverse=True)
                top3_share = sum(s[1] for s in shares[:3])
                total_entities = len(shares)

                if top3_share > 0.60:  # top 3 entities > 60% of total
                    top3_names = ", ".join(s[0] for s in shares[:3])
                    detail = (
                        f"Concentration risk in {m} ({level_key}): top 3 of {total_entities} entities "
                        f"({top3_names}) account for {top3_share*100:.0f}% of total"
                    )
                    score = min((top3_share - 0.60) * 2, 0.8)
                    self.add_signal(score, "Concentration", f"{m} {level_key} concentrated",
                                   detail, m, "concentration_risk")

    def extract_price_volume_decomposition(self):
        """When revenue + volume metrics exist, decompose variance into price vs volume effects."""
        totals = BriefUtils.get_network_totals(self.metrics)
        if len(totals) < 2:
            return

        # Find revenue-like and volume-like metrics by name heuristics
        revenue_metrics = {}
        volume_metrics = {}
        for name, data in totals.items():
            lower = name.lower()
            if any(kw in lower for kw in ["rev", "dollar", "sales", "amount", "price", "cost"]):
                revenue_metrics[name] = data
            elif any(kw in lower for kw in ["count", "volume", "quantity", "bottles", "units", "orders", "miles", "liters", "gallons"]):
                volume_metrics[name] = data

        if not revenue_metrics or not volume_metrics:
            return

        # For each revenue-volume pair, decompose
        for rev_name, rev_data in revenue_metrics.items():
            for vol_name, vol_data in volume_metrics.items():
                rev_pct = rev_data.get("var_pct", 0)
                vol_pct = vol_data.get("var_pct", 0)

                if rev_pct is None or vol_pct is None:
                    continue

                rev_pct = float(rev_pct)
                vol_pct = float(vol_pct)

                # Price effect = revenue change - volume change (approximate)
                price_effect = rev_pct - vol_pct

                if abs(price_effect) < 1.0:
                    # Revenue and volume moving together = no price effect
                    continue

                if abs(rev_pct) < 2.0 and abs(vol_pct) < 2.0:
                    # Both too small to decompose meaningfully
                    continue

                score = min(abs(price_effect) * 0.03, 0.8)

                if price_effect > 0 and vol_pct >= 0:
                    detail = (
                        f"Price/yield improvement: {rev_name} {rev_pct:+.1f}% vs {vol_name} {vol_pct:+.1f}% "
                        f"(+{price_effect:.1f}pts price effect) — getting more per unit"
                    )
                    category = "Price Improvement"
                elif price_effect < 0 and vol_pct >= 0:
                    detail = (
                        f"Price/yield compression: {rev_name} {rev_pct:+.1f}% vs {vol_name} {vol_pct:+.1f}% "
                        f"({price_effect:+.1f}pts price effect) — moving volume at lower rates"
                    )
                    category = "Price Compression"
                elif price_effect > 0 and vol_pct < 0:
                    detail = (
                        f"Volume decline offset by pricing: {vol_name} {vol_pct:+.1f}% but {rev_name} {rev_pct:+.1f}% "
                        f"(+{price_effect:.1f}pts price effect) — fewer units at higher prices"
                    )
                    category = "Mix Shift"
                else:
                    detail = (
                        f"Double compression: {rev_name} {rev_pct:+.1f}% and {vol_name} {vol_pct:+.1f}% "
                        f"({price_effect:+.1f}pts price effect) — losing both volume and pricing power"
                    )
                    category = "Double Compression"
                    score = min(score * 1.5, 1.0)  # extra severity

                self.add_signal(score, category, f"{rev_name} vs {vol_name} decomposition",
                               detail, "cross_metric", "price_volume_decomp")

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

def merge_pass1_kept_into_signals(
    signals: List[Dict[str, Any]], kept_rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Attach Pass 1 structured fields to signals, ordered by Pass 1 rank (ascending)."""
    by_id = {s["id"]: s for s in signals}
    out: List[Dict[str, Any]] = []
    for row in sorted(kept_rows, key=lambda r: (r.get("rank") is None, r.get("rank", 999))):
        sid = row.get("id")
        if not sid or sid not in by_id:
            continue
        merged = dict(by_id[sid])
        merged["one_line_why"] = row.get("one_line_why", "")
        merged["executive_category"] = row.get("category", "")
        merged["metric_description"] = row.get("metric_description", "")
        merged["clean_name"] = row.get("clean_name", "")
        merged["dimension"] = row.get("dimension", "")
        merged["pass1_rank"] = row.get("rank")
        out.append(merged)
    return out


def pass1_curate(client, model: str, totals: Dict[str, Any], signals: List[Dict[str, Any]], max_curated: int) -> Dict[str, Any]:
    """Pass 1: Flash-Lite selects the most important signals from the ranked pool."""
    from google.genai import types
    import time

    _style = os.environ.get("EXECUTIVE_BRIEF_STYLE", "").lower()
    _auditor = _style == "billing_auditor"

    input_signals = []
    for s in signals:
        row: Dict[str, Any] = {
            "id": s["id"],
            "signal_type": s["category"],
            "title": s.get("title", ""),
            "detail": s["detail"],
            "metric_key": s["metric"],
            "score": s["score"],
        }
        if s.get("entity") is not None:
            row["entity"] = s["entity"]
        if s.get("var_pct") is not None:
            row["var_pct"] = s["var_pct"]
        if s.get("current_value") is not None:
            row["current_value"] = s["current_value"]
        if s.get("prior_value") is not None:
            row["prior_value"] = s["prior_value"]
        input_signals.append(row)

    valid_ids = {s["id"] for s in signals}
    if not input_signals:
        return {
            "kept": [],
            "dropped": [],
            "narrative_thesis": "No ranked signals available for this period.",
            "_elapsed": 0.0,
        }

    _role = (
        "You are a billing auditor and revenue-assurance analyst. You have ranked toll and operational signals.\n"
        f"Select the TOP {max_curated} signals that best indicate **customers (shipper parents), shippers, or lanes** "
        "where **billing, rating, or accruals** should be reviewed (revenue vs expense vs recommended toll mismatches, "
        "unusual WoW swings, concentration risk).\n"
        if _auditor
        else (
            "You are a senior analyst for a trucking company. You have a list of ranked operational signals (deterministic stats).\n"
            f"Your job is to select the TOP {max_curated} most impactful and coherent signals for an executive CEO brief.\n"
        )
    )
    _cover = (
        "ENSURE coverage across toll revenue, toll expense, and recommended toll cost when material; "
        "prioritize named shipper parents and lanes.\n\n"
        if _auditor
        else "ENSURE coverage across Revenue, Efficiency, and Capacity if significant moves exist.\n\n"
    )
    _cat_desc = (
        "billing / assurance theme — one of: Revenue, Cost alignment, Recommended vs actual, Lane anomaly, "
        "Customer concentration, Accrual risk, Network, Other.\n"
        if _auditor
        else "executive theme bucket — one of: Revenue, Efficiency, Utilization, Capacity, Yield, Cost, Network, Other.\n"
    )
    prompt = (
        _role
        + (
            "CRITICAL: Every kept id MUST match an id from RANKED SIGNALS exactly (same string). Never invent or rename ids.\n"
            "DROP signals that are noise, contradictory, or redundant across metrics.\n"
        )
        + _cover
        + "For EACH kept signal, also output:\n"
        + "- category: "
        + _cat_desc
        + "- metric_description: ONE line in this EXACT pattern (no extra words before/after):\n"
        + '  \"{clean_name} - {slice}: {+/-X.X}% WoW | {current_fmt} vs {prior_fmt}.\"\n'
        + "  - clean_name: short label (e.g. \"Deadhead %\", \"Total Revenue\", \"Total Miles\").\n"
        + "  - slice: entity/region name ONLY (e.g. Manteno, East, Gary), or \"Network\" for network-wide or cross_metric signals.\n"
        + "  - WoW: use var_pct from the signal with one decimal and a leading + or - (e.g. +28.7% WoW).\n"
        + "  - current_fmt vs prior_fmt: format using current_value and prior_value when present in the signal JSON. "
        + "Use correct units: *_pct / deadhead → one-decimal percentages (e.g. 18.2% vs 14.1%); currency metrics → $ with K/M suffixes; "
        + "miles → compact mi. Never use $ for pure percentage metrics.\n"
        + "  - If current_value or prior_value is missing, end after WoW only: \"{clean_name} - {slice}: {+/-X.X}% WoW.\" "
        + "Do not invent levels.\n"
        + "- clean_name: same short metric label as embedded in metric_description.\n"
        + "- dimension: scope for filtering. Use \"Region: East\" / \"Location: Gary\" when sliced; \"Network\" when not sliced.\n\n"
        + "NETWORK TOTALS (for context):\n"
    )
    for m, d in totals.items():
        line = f"- {m}: {d['var_pct']:+.1f}% WoW (${abs(d['var_dollar']):,.0f})"
        if d.get("current") is not None:
            line += f", current {format_brief_current_value(d['current'])}"
        prompt += line + "\n"

    prompt += "\nRANKED SIGNALS (from Pass 0):\n"
    prompt += json.dumps(input_signals, indent=2)

    schema = types.Schema(type=types.Type.OBJECT, properties={
        "kept": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
            "id": types.Schema(type=types.Type.STRING),
            "rank": types.Schema(type=types.Type.INTEGER),
            "one_line_why": types.Schema(type=types.Type.STRING),
            "category": types.Schema(
                type=types.Type.STRING,
                description="Executive theme: Revenue, Efficiency, Utilization, Capacity, Yield, Cost, Network, or Other.",
            ),
            "metric_description": types.Schema(
                type=types.Type.STRING,
                description=(
                    'Format: "{clean_name} - {slice}: ±X.X% WoW | current vs prior." '
                    "Use signal current_value/prior_value when present; else end after WoW."
                ),
            ),
            "clean_name": types.Schema(type=types.Type.STRING, description="Short human-readable metric name."),
            "dimension": types.Schema(
                type=types.Type.STRING,
                description='Scope e.g. "Region: East" or "Network".',
            ),
        }, required=[
            "id",
            "rank",
            "one_line_why",
            "category",
            "metric_description",
            "clean_name",
            "dimension",
        ])),
        "dropped": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
            "id": types.Schema(type=types.Type.STRING),
            "reason": types.Schema(type=types.Type.STRING)
        }, required=["id", "reason"])),
        "narrative_thesis": types.Schema(
            type=types.Type.STRING,
            description=(
                "One sentence: billing assurance thesis for the week (auditor mode), or week's performance (CEO mode)."
            ),
        )
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
    raw_kept = list(curation.get("kept") or [])
    kept_ok = [k for k in raw_kept if isinstance(k, dict) and k.get("id") in valid_ids]
    if len(kept_ok) != len(raw_kept):
        for k in raw_kept:
            if isinstance(k, dict) and k.get("id") not in valid_ids:
                curation.setdefault("dropped", [])
                if isinstance(curation["dropped"], list):
                    curation["dropped"].append(
                        {
                            "id": str(k.get("id", "")),
                            "reason": "Invalid id (not in Pass 0 signal list).",
                        }
                    )
    for i, row in enumerate(sorted(kept_ok, key=lambda r: (r.get("rank") is None, r.get("rank", 999))), start=1):
        row["rank"] = i
    curation["kept"] = kept_ok
    return curation

def pass2_brief(client, model: str, totals: Dict[str, Any], signals: List[Dict[str, Any]], thesis: str, period: str) -> Dict[str, Any]:
    """Pass 2: Synthesize final CEO or billing-auditor brief from curated signals."""
    from google.genai import types
    import time

    _style = os.environ.get("EXECUTIVE_BRIEF_STYLE", "").lower()
    _prompt_name = (
        "executive_brief_billing_auditor.md"
        if _style == "billing_auditor"
        else "executive_brief_ceo.md"
    )
    prompt_template = (PROJECT_ROOT / "config" / "prompts" / _prompt_name).read_text(encoding="utf-8").strip()
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
        cur_fmt = format_brief_current_value(d.get("current"))
        user_msg += (
            f"- {m}: {d['var_pct']:+.1f}% WoW (${abs(d['var_dollar']):,.0f}), current {cur_fmt}\n"
        )
    
    user_msg += "\nCURATED INSIGHTS (use ONLY these signals, preserve exact numbers):\n"
    for i, s in enumerate(signals, 1):
        user_msg += f"{i}. [{s['category']}] {s['detail']}\n"

    user_msg += (
        "\nGROUNDING (mandatory):\n"
        "- Every numeric claim must come verbatim from NETWORK TOTALS or CURATED INSIGHTS above. "
        "Do not invent revenue bands, dollar outlook ranges, or scenario numbers.\n"
        "- Never mirror the same percentage across two different metrics (e.g. deadhead change in pts "
        "vs LRPM in $/mi). State the unit explicitly for each figure (pts, % WoW, $, etc.).\n"
        "- why_it_matters: Explain the business impact and significance of the observed trends, articulating the specific causal mechanisms or drivers and their quantified impact where possible. Focus on the 'so what?' for the business, referencing exact numbers from insights to support claims of impact.\n"
        "- next_week_outlook: qualitative or mechanism-only unless a specific number appears in the "
        "signals above; do not add best/worst-case dollar ranges.\n"
        "- leadership_focus: Each point must be a concrete, actionable recommendation, explaining its connection to a specific trend or cause identified in the insights, referencing the exact data or numbers that support it.\n"
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
