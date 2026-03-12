"""Data Analyst Agent - Multi-agent P&L variance analysis pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

__version__ = "1.0.0"
__build__ = "2026-03-12"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_SITE_PACKAGES = _REPO_ROOT / ".venv" / f"lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"

if _VENV_SITE_PACKAGES.exists():
    site_packages_path = str(_VENV_SITE_PACKAGES)
    if site_packages_path not in sys.path:
        sys.path.insert(0, site_packages_path)
