import time
from typing import AsyncGenerator
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from pydantic import Field

class TimedAgentWrapper(BaseAgent):
    """Wraps an agent to measure and log its execution time."""
    wrapped_agent: BaseAgent = Field(..., exclude=True)

    def __init__(self, agent: BaseAgent):
        super().__init__(name=f"timed_{agent.name}", wrapped_agent=agent)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        start_time = time.perf_counter()
        print(f"\n[TIMER] >>> Starting agent: {self.wrapped_agent.name}")
        
        try:
            async for event in self.wrapped_agent.run_async(ctx):
                yield event
        finally:
            end_time = time.perf_counter()
            duration = end_time - start_time
            print(f"[TIMER] <<< Finished agent: {self.wrapped_agent.name} | Duration: {duration:.2f}s\n")
