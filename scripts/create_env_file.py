#!/usr/bin/env python3
"""
Create .env file with phase logging configuration.

This script generates a .env file from the template with sensible defaults
and phase logging enabled.

Usage:
    python scripts/create_env_file.py
"""

import os
from pathlib import Path

# Project root
project_root = Path(__file__).parent.parent

def create_env_file():
    """Create .env file with phase logging configuration."""
    
    env_file = project_root / ".env"
    
    # Check if .env already exists
    if env_file.exists():
        response = input(f".env file already exists at {env_file}. Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Cancelled. No changes made.")
            return
    
    # Environment content
    env_content = """# Google Cloud Authentication Configuration
# Configure your authentication method below

# === OPTION 1: Service Account (RECOMMENDED for Production) ===
# Path to your service account JSON file
# GOOGLE_APPLICATION_CREDENTIALS=./service-account.json
# GOOGLE_APPLICATION_CREDENTIALS=C:/path/to/your-project-abc123.json

# === OPTION 2: API Key (For Testing Only) ===
# Your Google API Key
# GOOGLE_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

# === OPTION 3: Application Default Credentials (ADC) ===
# No configuration needed - uses gcloud CLI authentication
# Run: gcloud auth application-default login

# === Project Configuration ===
# Your Google Cloud Project ID
GOOGLE_CLOUD_PROJECT=vertex-ai-bi-testing
GOOGLE_CLOUD_LOCATION=us-central1

# === Model Configuration ===
ROOT_AGENT_MODEL=gemini-2.5-pro
MODEL_TEMPERATURE=0.0

# === A2A Server Configuration ===
A2A_BASE_URL=http://localhost:8001
A2A_SERVER_PORT=8001

# === Rate Limiting (for parallel execution) ===
GOOGLE_GENAI_RPM_LIMIT=5
GOOGLE_GENAI_RETRY_DELAY=3
GOOGLE_GENAI_MAX_RETRIES=5
GOOGLE_GENAI_EXPONENTIAL_BACKOFF=True
GOOGLE_GENAI_BACKOFF_MULTIPLIER=2

# === Test Mode ===
# Set to "true" to use CSV data instead of Tableau A2A agents
PL_ANALYST_TEST_MODE=false

# === Phase Logging Configuration ===
# Enable phase-based logging for each analysis phase
PHASE_LOGGING_ENABLED=true

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
PHASE_LOG_LEVEL=INFO

# Directory for phase log files (relative to project root)
PHASE_LOG_DIRECTORY=logs

# Save JSON summary after each cost center analysis
PHASE_LOG_SAVE_SUMMARY=true

# Log format: simple, detailed, json
PHASE_LOG_CONSOLE_FORMAT=detailed

# Track performance metrics for each phase
PHASE_LOG_TRACK_PERFORMANCE=true

# Log stack traces on errors
PHASE_LOG_STACK_TRACES=true
"""
    
    # Write the file
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(env_content)
    
    print("="*80)
    print("✓ .env file created successfully!")
    print("="*80)
    print(f"\nLocation: {env_file}")
    print("\nPhase logging is ENABLED with the following settings:")
    print("  - Log Level: INFO")
    print("  - Log Directory: logs/")
    print("  - Console Format: detailed")
    print("  - Performance Tracking: ON")
    print("  - Save Summaries: ON")
    print("\nNext Steps:")
    print("  1. Review and customize settings in .env")
    print("  2. Configure authentication (uncomment one of the auth options)")
    print("  3. Run: python scripts/setup_phase_logging.py")
    print("  4. Test with: python test_with_csv.py")
    print("="*80)

if __name__ == "__main__":
    create_env_file()

