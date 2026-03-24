import atexit
import sys
import os
from pathlib import Path

def start_dependency_tracking():
    """
    Registers an atexit handler to track which project files were actually imported
    during the execution. Results are written to the current run's output directory.
    """
    # Capture the project root at import time
    project_root = Path(__file__).parent.parent.parent.resolve()

    def on_exit():
        # 1. Identify all .py files in the project
        all_project_files = set()
        for path in project_root.rglob("*.py"):
            # Skip common non-source directories
            if any(part.startswith(".") or part == "__pycache__" or part == "venv" or part == "node_modules" for part in path.parts):
                continue
            all_project_files.add(str(path.resolve()))

        # 2. Identify all touched files from sys.modules
        touched_files = set()
        for name, module in list(sys.modules.items()):
            try:
                if hasattr(module, "__file__") and module.__file__:
                    file_path = Path(module.__file__).resolve()
                    if str(file_path).startswith(str(project_root)):
                        touched_files.add(str(file_path))
            except Exception:
                # Some modules might have weird __file__ attributes or fail to resolve
                continue

        # 3. Calculate untouched files
        untouched_files = all_project_files - touched_files

        # 4. Determine where to write the reports
        # Use the environment variable set by the agent/CLI
        output_dir_str = os.environ.get("DATA_ANALYST_OUTPUT_DIR")
        if not output_dir_str:
            # Fallback to current directory or a default location if output_dir isn't set yet
            output_dir_str = "."
        
        output_dir = Path(output_dir_str)
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                # If we can't create the directory, just log to stdout as a last resort
                print(f"[DependencyTracker] WARNING: Could not create output directory {output_dir}")
                output_dir = Path(".")

        # 5. Write reports
        try:
            touched_report = output_dir / "touched_files.txt"
            untouched_report = output_dir / "untouched_files.txt"

            with open(touched_report, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(touched_files)))
            
            with open(untouched_report, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(untouched_files)))

            print(f"[DependencyTracker] Reports written to {output_dir}")
            print(f"  - Touched: {len(touched_files)}")
            print(f"  - Untouched: {len(untouched_files)}")
        except Exception as e:
            print(f"[DependencyTracker] ERROR writing reports: {e}")

    atexit.register(on_exit)

# Auto-start if imported
start_dependency_tracking()
