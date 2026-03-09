"""
HyperConnectionManager
======================

Manages the lifecycle of a Tableau Hyper dataset:
  1. Extracts a ``.hyper`` file from a ``.tdsx`` archive (once per session).
  2. Opens and maintains a persistent ``HyperProcess`` + ``Connection``.
  3. Health-checks the connection before every query and reconnects on failure.
  4. Executes SQL queries and returns results as Pandas DataFrames.
  5. Cleans up the process and connection on interpreter exit (``atexit``).

One ``HyperConnectionManager`` instance per dataset is the intended pattern.
The ``TableauHyperFetcher`` agent owns an instance scoped to a single agent run.
"""

from __future__ import annotations

import atexit
import glob as glob_mod
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from tableauhyperapi import HyperProcess, Connection, Telemetry
    HYPER_API_AVAILABLE = True
except ImportError:
    HYPER_API_AVAILABLE = False
    HyperProcess = None  # type: ignore[assignment,misc]
    Connection = None    # type: ignore[assignment,misc]

from .loader_config import HyperLoaderConfig


# ---------------------------------------------------------------------------
# Module-level registry: reuse managers across agent re-imports
# ---------------------------------------------------------------------------

_MANAGERS: Dict[str, "HyperConnectionManager"] = {}


def get_or_create_manager(dataset_key: str, config: HyperLoaderConfig) -> "HyperConnectionManager":
    """Return a cached manager for *dataset_key*, creating one if needed."""
    if dataset_key not in _MANAGERS:
        _MANAGERS[dataset_key] = HyperConnectionManager(dataset_key, config)
    return _MANAGERS[dataset_key]


# ---------------------------------------------------------------------------
# HyperConnectionManager
# ---------------------------------------------------------------------------

class HyperConnectionManager:
    """Manages extraction and persistent querying of a single Hyper dataset."""

    def __init__(self, dataset_key: str, config: HyperLoaderConfig) -> None:
        self._key = dataset_key
        self._config = config

        self._hyper_path: Optional[str] = None
        self._process: Optional[HyperProcess] = None
        self._connection: Optional[Connection] = None
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_extracted(self, project_root: Path) -> str:
        """Extract the ``.hyper`` from the TDSX archive if not already done.

        Re-uses an existing ``.hyper`` file in the extract directory so that
        parallel workers sharing the same file system do not re-extract.
        If the TDSX file is newer than the cached Hyper, it re-extracts.

        Returns:
            Absolute path to the extracted ``.hyper`` file.

        Raises:
            FileNotFoundError: If the TDSX file does not exist.
            ImportError: If ``tableauhyperapi`` is not installed.
        """
        if not HYPER_API_AVAILABLE:
            raise ImportError(
                "[HyperConnectionManager] tableauhyperapi is not installed. "
                "Install it with: pip install tableauhyperapi"
            )

        tdsx_path = self._config.resolve_tdsx_path(project_root)
        extract_dir = self._config.resolve_extract_dir(project_root)

        # Determine TDSX modification time if it exists
        tdsx_mtime = 0.0
        if tdsx_path.exists():
            tdsx_mtime = os.path.getmtime(str(tdsx_path))

        # In-memory fast path -- but invalidate if TDSX is newer
        if self._hyper_path and os.path.exists(self._hyper_path):
            if os.path.getmtime(self._hyper_path) >= tdsx_mtime:
                return self._hyper_path

        extract_dir.mkdir(parents=True, exist_ok=True)

        # Reuse an existing .hyper file if it's fresh enough
        existing = glob_mod.glob(
            os.path.join(str(extract_dir), "**", "*.hyper"), recursive=True
        )
        if existing:
            candidate = existing[0]
            if os.path.getmtime(candidate) >= tdsx_mtime:
                try:
                    with open(candidate, "rb"):
                        pass
                except (PermissionError, OSError) as lock_err:
                    print(
                        f"[{self._key}] Hyper file may be locked ({lock_err}). "
                        f"Reusing: {candidate}"
                    )
                self._hyper_path = candidate
                print(f"[{self._key}] Reusing extracted Hyper file: {candidate}")
                return self._hyper_path
            else:
                # Stale cache -- purge and re-extract
                print(
                    f"[{self._key}] TDSX is newer than cached Hyper ({tdsx_path.name}) -- re-extracting"
                )
                try:
                    shutil.rmtree(extract_dir)
                except Exception as e:
                    print(f"[{self._key}] Warning: could not clean extract_dir: {e}")
                extract_dir.mkdir(parents=True, exist_ok=True)

        if not tdsx_path.exists():
            raise FileNotFoundError(
                f"[{self._key}] TDSX file not found: {tdsx_path}. "
                f"Place '{self._config.hyper.tdsx_file}' in '{self._config.hyper.tdsx_path}/'."
            )

        print(f"[{self._key}] Extracting Hyper from {tdsx_path.name}...")
        self._hyper_path = self._extract_hyper_from_tdsx(
            str(tdsx_path), str(extract_dir)
        )
        print(f"[{self._key}] Extracted to: {self._hyper_path}")
        return self._hyper_path

    def get_connection(self) -> "Connection":
        """Return a healthy persistent Connection, reconnecting if stale.

        Raises:
            RuntimeError: If the connection cannot be established after retries.
        """
        if not self._initialized or self._connection is None:
            self._init_connection()
            return self._connection  # type: ignore[return-value]

        # Health check
        try:
            with self._connection.execute_query("SELECT 1") as _:
                pass
        except Exception:
            if not self._try_reconnect():
                raise RuntimeError(
                    f"[{self._key}] Hyper connection lost and all reconnection attempts failed."
                )
        return self._connection  # type: ignore[return-value]

    def execute_query(self, sql: str) -> "pd.DataFrame":
        """Execute *sql* against the Hyper file and return a DataFrame.

        Args:
            sql: A valid SQL query in Hyper/Postgres dialect.

        Returns:
            A ``pd.DataFrame`` containing the query results.
        """
        if not PANDAS_AVAILABLE:
            raise ImportError("[HyperConnectionManager] pandas is required but not installed.")

        conn = self.get_connection()
        with conn.execute_query(sql) as result_set:
            columns = [col.name.unescaped for col in result_set.schema.columns]
            rows = [list(row) for row in result_set]

        return pd.DataFrame(rows, columns=columns)

    def execute_query_to_csv(self, sql: str) -> str:
        """Execute *sql* and return the result as a CSV string."""
        return self.execute_query(sql).to_csv(index=False)

    def is_ready(self) -> bool:
        """Return True if the Hyper file is present and the connection is live."""
        return (
            self._hyper_path is not None
            and os.path.exists(self._hyper_path)
            and self._initialized
            and self._connection is not None
        )

    def get_hyper_path(self) -> Optional[str]:
        return self._hyper_path

    def get_default_table(self) -> str:
        return self._config.hyper.default_table

    def cleanup(self) -> None:
        """Close the Connection and HyperProcess."""
        try:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            if self._process is not None:
                self._process.close()
                self._process = None
        except Exception as exc:
            print(f"[{self._key}] Warning during cleanup: {exc}")
        finally:
            self._initialized = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _init_connection(self) -> None:
        if not self._hyper_path or not os.path.exists(self._hyper_path):
            raise RuntimeError(
                f"[{self._key}] Hyper file not available. Call ensure_extracted() first."
            )
        log_dir = Path(tempfile.gettempdir()) / f"hyper_logs_{self._key}_{os.getpid()}"
        log_dir.mkdir(exist_ok=True)

        self._process = HyperProcess(
            telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
            parameters={"log_dir": str(log_dir)},
        )
        self._connection = Connection(
            endpoint=self._process.endpoint,
            database=self._hyper_path,
        )
        self._initialized = True
        atexit.register(self.cleanup)
        print(f"[{self._key}] Persistent Hyper connection initialized.")

    def _try_reconnect(self, max_attempts: int = 3, backoff_s: float = 2.0) -> bool:
        print(f"[{self._key}] Connection failure detected. Attempting recovery...")
        self.cleanup()
        for attempt in range(1, max_attempts + 1):
            try:
                self._init_connection()
                if self._initialized and self._connection is not None:
                    print(f"[{self._key}] Recovery succeeded on attempt {attempt}.")
                    return True
            except Exception as exc:
                print(f"[{self._key}] Recovery attempt {attempt} failed: {exc}")
            if attempt < max_attempts:
                time.sleep(backoff_s * attempt)
        print(f"[{self._key}] All {max_attempts} recovery attempts failed.")
        return False

    @staticmethod
    def _extract_hyper_from_tdsx(tdsx_path: str, extract_dir: str) -> str:
        """Extract a ``.hyper`` file from a ``.tdsx`` ZIP archive.

        Falls back to an inline implementation so that this module does not
        hard-depend on ``remote_a2a`` being on the Python path.
        """
        # Prefer the shared library if available
        try:
            import sys as _sys
            # Locate project root (two levels above this file:
            # sub_agents/tableau_hyper_fetcher/ -> sub_agents/ -> data_analyst_agent/ -> pl_analyst/)
            _here = Path(__file__).parent
            _project = _here.parent.parent.parent.parent
            if str(_project) not in _sys.path:
                _sys.path.insert(0, str(_project))
            from remote_a2a.utils.tableau_shared.tdsx import extract_hyper_from_tdsx
            return extract_hyper_from_tdsx(tdsx_path, extract_dir)
        except ImportError:
            pass

        # Inline fallback
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(tdsx_path, "r") as zf:
            zf.extractall(extract_dir)
        found = glob_mod.glob(
            os.path.join(extract_dir, "**", "*.hyper"), recursive=True
        )
        if not found:
            raise ValueError(f"No .hyper file found in TDSX archive: {tdsx_path}")
        return found[0]
