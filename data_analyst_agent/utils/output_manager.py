import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

class OutputManager:
    """
    Manages structured, hierarchical output directories for analysis runs.
    
    Structure:
    outputs/{dataset}/{dimension}/{dimension_value}/{timestamp}_{run_id}/
    """
    
    def __init__(
        self, 
        dataset: str, 
        dimension: Optional[str] = None, 
        dimension_value: Optional[str] = None,
        run_id: Optional[str] = None,
        root_dir: Optional[str] = None
    ):
        self.dataset = dataset
        self.dimension = dimension or "global"
        self.dimension_value = dimension_value or "all"
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = run_id or self.timestamp
        
        # Determine root outputs directory
        env_root = os.getenv("DATA_ANALYST_OUTPUT_ROOT")
        self.root_dir = Path(root_dir or env_root or "outputs").resolve()
        
        # Generate the run-specific directory path
        self.run_dir = self._generate_run_dir()
        
    def _generate_run_dir(self) -> Path:
        """Generate the full path for the current run."""
        # Sanitize components for filesystem
        safe_dataset = self._sanitize(self.dataset)
        safe_dimension = self._sanitize(self.dimension)
        safe_value = self._sanitize(self.dimension_value)
        
        run_folder = f"{self.run_id}"
        
        path = self.root_dir / safe_dataset / safe_dimension / safe_value / run_folder
        return path

    def _sanitize(self, name: str) -> str:
        """Sanitize a string for use as a directory name."""
        return str(name).replace(" ", "_").replace("/", "-").replace("\\", "-").replace(":", "-")

    def create_run_directory(self) -> Path:
        """Ensure the run directory exists."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # Also ensure logs subdirectory exists
        (self.run_dir / "logs").mkdir(exist_ok=True)
        return self.run_dir

    def get_file_path(self, filename: str) -> Path:
        """Get the absolute path for a file within the run directory."""
        return self.run_dir / filename

    def get_log_path(self, filename: str) -> Path:
        """Get the absolute path for a log file within the logs subdirectory."""
        return self.run_dir / "logs" / filename

    def save_run_metadata(self, cli_args: Dict[str, Any], extra_metadata: Optional[Dict[str, Any]] = None):
        """Save metadata about the run to run_metadata.json."""
        metadata = {
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(),
            "dataset": self.dataset,
            "dimension": self.dimension,
            "dimension_value": self.dimension_value,
            "cli_arguments": cli_args,
            "environment": {
                "ACTIVE_DATASET": os.getenv("ACTIVE_DATASET"),
                "DATA_ANALYST_METRICS": os.getenv("DATA_ANALYST_METRICS"),
            }
        }
        if extra_metadata:
            metadata.update(extra_metadata)
            
        metadata_path = self.get_file_path("run_metadata.json")
        self.create_run_directory()
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return metadata_path

    @classmethod
    def from_env(cls) -> Optional['OutputManager']:
        """Initialize OutputManager from environment variables if they exist."""
        dataset = os.getenv("ACTIVE_DATASET")
        if not dataset:
            return None
            
        return cls(
            dataset=dataset,
            dimension=os.getenv("DATA_ANALYST_DIMENSION"),
            dimension_value=os.getenv("DATA_ANALYST_DIMENSION_VALUE"),
            run_id=os.getenv("DATA_ANALYST_RUN_ID")
        )
