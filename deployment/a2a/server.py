"""A2A Protocol server for data_analyst_agent integration with Agent Garden."""
import os
from google.adk.a2a import to_a2a, AgentCardBuilder
from google.adk.sessions import InMemorySessionService
from data_analyst_agent.agent import root_agent
from data_analyst_agent.logging_config import setup_logging

logger = setup_logging(__name__)

# Initialize session service
session_service = InMemorySessionService()

# Convert to A2A-compatible server
try:
    a2a_app = to_a2a(
        agent=root_agent,
        session_service=session_service
    )
    logger.info("A2A server initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize A2A server: {e}")
    raise

# Create agent card for Agent Garden discovery
agent_card = AgentCardBuilder(
    name="data_analyst_agent",
    description="Multi-agent P&L variance analysis pipeline with hierarchical drill-down. "
                "Performs automated anomaly detection, statistical analysis, and narrative "
                "synthesis across time-series financial data.",
    capabilities=[
        "anomaly_detection",
        "variance_analysis",
        "executive_reporting",
        "hierarchical_analysis",
        "seasonal_decomposition",
        "statistical_insights"
    ],
    supported_protocols=["a2a/v0.3"],
    version=os.getenv("APP_VERSION", "1.0.0"),
    author="Ty Hayes",
    icon_url=os.getenv("AGENT_ICON_URL", ""),
    tags=["finance", "analytics", "multi-agent", "adk"]
).build()


def get_agent_card():
    """Return the agent card for discovery."""
    return agent_card


# For uvicorn: uvicorn deployment.a2a.server:a2a_app --host 0.0.0.0 --port 8000
