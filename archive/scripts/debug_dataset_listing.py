import os
import sys
from pathlib import Path
import yaml

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.contract_loader import list_datasets

print("Listing datasets discovered by web/contract_loader.py:")
datasets = list_datasets()
for d in datasets:
    print(f"ID: {d['id']}, Name: {d['name']}, Display Name: {d['display_name']}")

if not datasets:
    print("No datasets found!")

print("\nChecking DATASETS_DIR existence:")
DATASETS_DIR = Path(__file__).resolve().parent.parent / "config" / "datasets"
print(f"DATASETS_DIR: {DATASETS_DIR}")
print(f"Exists: {DATASETS_DIR.exists()}")
