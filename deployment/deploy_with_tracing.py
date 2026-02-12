# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Deployment script for P&L Analyst Agent with tracing enabled"""

import os
import sys

# Resolve project root to the pl_analyst directory
PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

import vertexai
from absl import app, flags
from dotenv import load_dotenv
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# Import the root agent
from pl_analyst_agent.agent import root_agent

FLAGS = flags.FLAGS
flags.DEFINE_string("project_id", None, "GCP project ID.")
flags.DEFINE_string("location", None, "GCP location.")
flags.DEFINE_string("bucket", None, "GCS bucket for staging (without gs://).")
flags.DEFINE_string("resource_id", None, "ReasoningEngine resource ID.")

flags.DEFINE_bool("list", False, "List all agents.")
flags.DEFINE_bool("create", False, "Creates a new agent.")
flags.DEFINE_bool("delete", False, "Deletes an existing agent.")
flags.mark_bool_flags_as_mutual_exclusive(["create", "delete"])


def create() -> None:
    """Creates an Agent Engine for the P&L Analyst agent with tracing enabled."""
    # Get environment variables for the deployment
    env_vars = {
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing"),
        "GOOGLE_CLOUD_LOCATION": os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        "ROOT_AGENT_MODEL": os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-pro"),
        "MODEL_TEMPERATURE": os.getenv("MODEL_TEMPERATURE", "0.0"),
        "A2A_BASE_URL": os.getenv("A2A_BASE_URL", "http://localhost:8001"),
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        "GOOGLE_GENAI_RPM_LIMIT": os.getenv("GOOGLE_GENAI_RPM_LIMIT", "5"),
        "GOOGLE_GENAI_RETRY_DELAY": os.getenv("GOOGLE_GENAI_RETRY_DELAY", "3"),
        "GOOGLE_GENAI_MAX_RETRIES": os.getenv("GOOGLE_GENAI_MAX_RETRIES", "5"),
        "GOOGLE_GENAI_EXPONENTIAL_BACKOFF": os.getenv("GOOGLE_GENAI_EXPONENTIAL_BACKOFF", "True"),
        "GOOGLE_GENAI_BACKOFF_MULTIPLIER": os.getenv("GOOGLE_GENAI_BACKOFF_MULTIPLIER", "2"),
    }
    
    adk_app = AdkApp(agent=root_agent, enable_tracing=True, env_vars=env_vars)

    # Create remote agent
    remote_agent = agent_engines.create(
        adk_app,
        display_name="pl_analyst_v1",
        description="P&L Analyst Agent for automated cost center analysis, anomaly detection, and actionable insights",
        requirements=[
            "google-adk (>=1.14.1)",
            "google-cloud-aiplatform[agent_engines] (>=1.91.0,<2.0.0)",
            "google-genai (>=1.32.0,<2.0.0)",
            "a2a-sdk (>=0.3.4,<0.4.0)",
            "pydantic (>=2.10.6,<3.0.0)",
            "python-dotenv (>=1.0.0)",
            "pandas (>=2.2.0)",
            "numpy (>=1.26)",
            "pyodbc (>=5.2.0)",
            "pyyaml (>=6.0.2)",
            "statsmodels (>=0.14.1)",
            "scipy (>=1.11)",
            "scikit-learn (>=1.4)",
            "pmdarima (>=2.0.4)",
            "python-dateutil (>=2.8.2)",
            "ruptures (>=1.1.9)",
            "matplotlib (>=3.8.0)",
            "absl-py (>=2.2.1)",
            "cloudpickle (>=3.1.1)",
        ],
        extra_packages=[
            "./pl_analyst_agent",
            "./config",
        ],
    )

    print(f"Created remote agent: {remote_agent.resource_name}")
    print(f"Agent Engine ID: {remote_agent.resource_name.split('/')[-1]}")
    print("\n🔍 Tracing is enabled! View traces at:")
    print("https://console.cloud.google.com/traces/list")


def delete(resource_id: str) -> None:
    """Deletes an existing Agent Engine."""
    remote_agent = agent_engines.get(resource_id)
    remote_agent.delete(force=True)
    print(f"Deleted remote agent: {resource_id}")


def list_agents() -> None:
    """Lists all deployed Agent Engines in the project/location."""
    remote_agents = agent_engines.list()
    template = (
        "\n{agent.name} (\"{agent.display_name}\")\n"
        "- Create time: {agent.create_time}\n"
        "- Update time: {agent.update_time}\n"
        "- Resource name: {agent.resource_name}\n"
    )
    remote_agents_string = "\n".join(template.format(agent=agent) for agent in remote_agents)
    print(f"All remote agents:{remote_agents_string}")


def main(argv: list[str]) -> None:
    del argv  # unused
    # Load .env from project root directory
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_path = os.path.join(project_root, '.env')
    load_dotenv(env_path)

    project_id = FLAGS.project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
    location = FLAGS.location or os.getenv("GOOGLE_CLOUD_LOCATION")
    bucket = FLAGS.bucket or os.getenv("GOOGLE_CLOUD_STORAGE_BUCKET")

    print(f"PROJECT: {project_id}")
    print(f"LOCATION: {location}")
    print(f"BUCKET: {bucket}")

    missing = []
    if not project_id:
        missing.append("GOOGLE_CLOUD_PROJECT")
    if not location:
        missing.append("GOOGLE_CLOUD_LOCATION")
    if not bucket:
        missing.append("GOOGLE_CLOUD_STORAGE_BUCKET")

    if missing:
        print("Missing required environment variables: " + ", ".join(missing))
        return

    vertexai.init(project=project_id, location=location, staging_bucket=f"gs://{bucket}")

    if FLAGS.list:
        list_agents()
    elif FLAGS.create:
        create()
    elif FLAGS.delete:
        if not FLAGS.resource_id:
            print("resource_id is required for delete")
            return
        delete(FLAGS.resource_id)
    else:
        print("Unknown command. Use --create, --list, or --delete")


if __name__ == "__main__":
    app.run(main)

