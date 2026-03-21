import json
import os
from typing import Any


class InsightCache:
    """File-based cache for insight cards and analysis artifacts.

    Saves/loads pipeline stage results to enable brief regeneration
    without re-running the full analysis pipeline.
    """

    STAGES = [
        "statistical_cards", "hierarchy_cards", "narrative_cards",
        "alerts", "synthesis", "digest"
    ]

    def __init__(self, output_dir: str):
        self.cache_dir = os.path.join(output_dir, ".cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def _stage_path(self, stage: str, metric: str = "") -> str:
        """Return file path for a cache entry."""
        if metric:
            return os.path.join(self.cache_dir, f"{stage}_{metric}.json")
        return os.path.join(self.cache_dir, f"{stage}.json")

    def save_stage(self, stage: str, metric: str, data: dict) -> str:
        """Save a pipeline stage result. Returns cache path."""
        path = self._stage_path(stage, metric)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return path

    def load_stage(self, stage: str, metric: str = "") -> dict | None:
        """Load cached stage result. Returns None if not cached."""
        path = self._stage_path(stage, metric)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_digest(self, digest: dict) -> str:
        """Save the pre-computed brief digest for re-use."""
        return self.save_stage("digest", "", digest)

    def get_digest(self) -> dict | None:
        """Load the pre-computed brief digest."""
        return self.load_stage("digest")

    def list_cached_metrics(self) -> list[str]:
        """Return list of metrics that have cached data."""
        metrics = set()
        if not os.path.exists(self.cache_dir):
            return []
        for f in os.listdir(self.cache_dir):
            if f.endswith(".json") and "_" in f:
                # e.g., "statistical_cards_ttl_rev_amt.json"
                # stage is everything before the last underscore-separated metric name
                # But stages can have underscores too, so parse differently
                for stage in self.STAGES:
                    prefix = f"{stage}_"
                    if f.startswith(prefix) and f.endswith(".json"):
                        metric = f[len(prefix):-len(".json")]
                        if metric:
                            metrics.add(metric)
        return sorted(metrics)

    def is_analysis_cached(self) -> bool:
        """True if digest is cached (brief can be regenerated)."""
        return self.get_digest() is not None

    def get_cache_summary(self) -> dict:
        """Return summary of what's cached."""
        metrics = self.list_cached_metrics()
        stages_by_metric = {}
        for metric in metrics:
            stages_by_metric[metric] = []
            for stage in self.STAGES:
                if self.load_stage(stage, metric) is not None:
                    stages_by_metric[metric].append(stage)
        return {
            "cache_dir": self.cache_dir,
            "has_digest": self.is_analysis_cached(),
            "metrics": metrics,
            "stages_by_metric": stages_by_metric,
        }
