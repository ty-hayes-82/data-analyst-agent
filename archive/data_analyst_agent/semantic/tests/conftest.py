import sys
from unittest.mock import MagicMock

# Mock missing dependencies to allow tests to run without loading the whole agent
MOCK_MODULES = [
    "ruptures",
    "ruptures.costs",
    "ruptures.detection",
    "google.adk",
    "google.adk.agents",
    "google.adk.agents.remote_a2a_agent",
    "google.adk.agents.remote_a2a_agent.AGENT_CARD_WELL_KNOWN_PATH",
    "a2a",
    "a2a.client",
    "a2a.types"
]

for mod_name in MOCK_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
