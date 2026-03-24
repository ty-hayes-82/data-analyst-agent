import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

class OutputManager:
    """Manages structured, hierarchical output directories for analysis runs.
    
    This class creates and manages organized output directories for pipeline runs,
    ensuring each run has a unique directory for artifacts (reports, logs, etc.).
    
    Directory Structure:
        outputs/
        └── {dataset}/
            └── {dimension}/
                └── {dimension_value}/
                    └── {run_id}/
                        ├── run_metadata.json
                        ├── executive_brief.json
                        ├── narrative_cards.json
                        └── logs/
                            ├── phase_timings.json
                            └── debug.log
    
    Use Cases:
        - CLI runs: Create organized output for each execution
        - Web UI: Store run artifacts for later retrieval
        - Multi-target analysis: Separate outputs per dimension value
        - Debugging: Centralized logs per run
    
    Example Paths:
        outputs/trade_data/line_of_business/Retail/20250312_143022/executive_brief.json
        outputs/ops_metrics/global/all/20250312_150135/logs/phase_timings.json
    
    Session Integration:
        OutputManager is created by OutputPersistenceAgent and stored in session
        state. Other agents can access it via:
        >>> mgr = ctx.session.state.get("output_manager")
        >>> report_path = mgr.get_file_path("custom_report.json")
    
    Attributes:
        dataset: Dataset name (e.g., "trade_data", "ops_metrics")
        dimension: Dimension name (e.g., "line_of_business", "global")
        dimension_value: Dimension value (e.g., "Retail", "all")
        run_id: Unique run identifier (default: timestamp)
        timestamp: ISO timestamp of run start
        root_dir: Absolute path to outputs root directory
        run_dir: Absolute path to this run's directory
    
    Environment Variables:
        DATA_ANALYST_OUTPUT_ROOT: Override default 'outputs/' root directory
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
        """Save run metadata to meta/run_metadata.json in the run directory.
        
        Creates a comprehensive metadata file documenting the run configuration,
        environment, and context. Useful for reproducing runs and debugging.
        
        Args:
            cli_args: Dict of CLI arguments/parameters for this run.
                Example: {"metrics": ["revenue", "orders"], "start_date": "2025-01-01"}
            extra_metadata: Optional additional metadata to include (merged into result).
        
        Returns:
            Path: Absolute path to saved run_metadata.json file.
        
        Metadata Structure:
            {
                "run_id": "20250312_143022",
                "timestamp": "2025-03-12T14:30:22.123456",
                "dataset": "trade_data",
                "dimension": "line_of_business",
                "dimension_value": "Retail",
                "cli_arguments": {...},
                "environment": {
                    "ACTIVE_DATASET": "trade_data",
                    "DATA_ANALYST_METRICS": "revenue,orders",
                    "DATA_ANALYST_FOCUS": "recent_weekly_trends",
                    "DATA_ANALYST_CUSTOM_FOCUS": "..."
                },
                ...extra_metadata
            }
        
        Example:
            >>> mgr = OutputManager("trade_data", "lob", "Retail")
            >>> mgr.save_run_metadata(
            ...     cli_args={"metrics": ["revenue"]},
            ...     extra_metadata={"model": "gemini-2.0-flash"}
            ... )
            PosixPath('/data/outputs/trade_data/lob/Retail/20250312_143022/meta/run_metadata.json')
        
        Note:
            - Automatically creates run directory if it doesn't exist
            - Captures key environment variables for reproducibility
            - JSON pretty-printed with 2-space indentation
        """
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
                "DATA_ANALYST_FOCUS": os.getenv("DATA_ANALYST_FOCUS"),
                "DATA_ANALYST_CUSTOM_FOCUS": os.getenv("DATA_ANALYST_CUSTOM_FOCUS"),
            }
        }
        if extra_metadata:
            metadata.update(extra_metadata)
            
        # Move run_metadata to meta/ subfolder
        meta_dir = self.run_dir / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = meta_dir / "run_metadata.json"
        
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
