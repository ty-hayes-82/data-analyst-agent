# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Safe Parallel Agent Wrapper
============================

Wraps ParallelAgent to isolate failures and prevent async generator crashes.
Each sub-agent's exceptions are caught individually without cascading to other agents.
"""

from typing import AsyncGenerator, List
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
import asyncio
import traceback


class SafeParallelWrapper(BaseAgent):
    """
    A safe wrapper for parallel agent execution that prevents cascading failures.
    
    Key features:
    - Catches exceptions per sub-agent without affecting others
    - Logs failures individually with full stack traces
    - Continues execution with partial results
    - Prevents async generator close errors during exception handling
    """
    
    def __init__(self, sub_agents: List[BaseAgent], name: str = "safe_parallel_wrapper"):
        """
        Initialize safe parallel wrapper.
        
        Args:
            sub_agents: List of agents to run in parallel
            name: Name for this wrapper agent
        """
        super().__init__(name=name)
        self.sub_agents = sub_agents
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        """
        Run all sub-agents in parallel with individual exception handling.
        
        Args:
            ctx: Invocation context
            
        Yields:
            Events from successful sub-agents
        """
        print(f"\n[{self.name}] Starting {len(self.sub_agents)} agents in parallel (safe mode)")
        
        async def run_one_agent_safely(agent: BaseAgent, index: int) -> List[Event]:
            """
            Run a single agent and collect all its events, catching any exceptions.
            
            Args:
                agent: The agent to run
                index: Index of this agent (for logging)
                
            Returns:
                List of events from the agent (empty if failed)
            """
            events = []
            try:
                print(f"[{self.name}] Starting agent {index + 1}/{len(self.sub_agents)}: {agent.name}")
                
                async for event in agent.run_async(ctx):
                    events.append(event)
                
                print(f"[{self.name}] [OK] Agent {index + 1}/{len(self.sub_agents)} completed: {agent.name} ({len(events)} events)")
                return events
                
            except Exception as e:
                error_msg = f"Agent {agent.name} failed with {type(e).__name__}: {str(e)}"
                print(f"[{self.name}] [ERROR] Agent {index + 1}/{len(self.sub_agents)} failed: {error_msg}")
                print(f"[{self.name}] Stack trace:\n{traceback.format_exc()}")
                
                # Create an error event to record the failure
                error_event = Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions()
                )
                return [error_event]
        
        # Run all agents concurrently, collecting results
        tasks = [
            run_one_agent_safely(agent, i)
            for i, agent in enumerate(self.sub_agents)
        ]
        
        # Gather all results (return_exceptions=False since we handle them inside run_one_agent_safely)
        all_results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Flatten and yield all events
        total_events = 0
        successful_agents = 0
        failed_agents = 0
        
        for agent_events in all_results:
            for event in agent_events:
                total_events += 1
                yield event
        
        # Count successful and failed from results length
        successful_agents = len([r for r in all_results if len(r) > 0])
        failed_agents = len(self.sub_agents) - successful_agents
        
        # Summary printed only (no event with text)
        summary = f"""
[{self.name}] Parallel execution complete:
  - Total agents: {len(self.sub_agents)}
  - Successful: {successful_agents}
  - Failed: {failed_agents}
  - Total events: {total_events}
"""
        print(summary)


def create_safe_parallel_agent(sub_agents: List[BaseAgent], name: str = "safe_parallel_agent") -> SafeParallelWrapper:
    """
    Create a safe parallel agent wrapper.
    
    Args:
        sub_agents: List of agents to run in parallel
        name: Name for the wrapper
        
    Returns:
        SafeParallelWrapper instance
        
    Example:
        ```python
        safe_analysis = create_safe_parallel_agent(
            sub_agents=[
                visualization_agent,
                descriptive_stats_agent,
                variance_calculation_agent,
                # ... more agents
            ],
            name="safe_parallel_analysis"
        )
        ```
    """
    return SafeParallelWrapper(sub_agents=sub_agents, name=name)


