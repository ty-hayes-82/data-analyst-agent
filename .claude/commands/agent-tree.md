# Agent Tree Visualization

Map the full agent hierarchy, data flow, and execution order.

## Steps

1. Read `data_analyst_agent/agent.py` to identify the root_agent and its sub_agents
2. For each sub-agent, read its `agent.py` to find nested sub_agents
3. Map the full tree including:
   - Agent name and type (Sequential, Loop, LLM, Base, Parallel)
   - Execution order within parent
   - State keys read and written
   - Tools registered

## Output Format

Produce an ASCII tree showing the full hierarchy with agent types, execution order, state dependencies, and tool registrations. Identify broken state dependencies (keys read but never written upstream), dead state (keys written but never read), and agents that could be parallelized.
