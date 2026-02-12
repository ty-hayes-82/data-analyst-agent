"""Test connectivity to Tableau A2A agents."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pl_analyst_agent.config import config


async def test_a2a_agent(agent_url: str, agent_name: str) -> bool:
    """Test connection to a single A2A agent."""
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Test agent info endpoint
            response = await client.get(f"{agent_url}/info")
            
            if response.status_code == 200:
                info = response.json()
                print(f"✅ {agent_name}")
                print(f"   URL: {agent_url}")
                print(f"   Status: Online")
                if "name" in info:
                    print(f"   Agent Name: {info['name']}")
                return True
            else:
                print(f"❌ {agent_name}")
                print(f"   URL: {agent_url}")
                print(f"   Status: HTTP {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ {agent_name}")
        print(f"   URL: {agent_url}")
        print(f"   Error: {str(e)}")
        return False


async def main():
    """Test all Tableau A2A agents."""
    print("=" * 60)
    print("P&L Analyst - Tableau A2A Connection Test")
    print("=" * 60)
    print(f"\nA2A Base URL: {config.a2a_base_url}\n")
    
    agents = [
        (f"{config.a2a_base_url}/tableau_account_research_ds_agent", "Tableau Account Research DS Agent"),
        (f"{config.a2a_base_url}/tableau_ops_metrics_ds_agent", "Tableau Ops Metrics DS Agent"),
        (f"{config.a2a_base_url}/tableau_order_dispatch_revenue_ds_agent", "Tableau Order Dispatch Revenue DS Agent"),
    ]
    
    results = []
    for agent_url, agent_name in agents:
        result = await test_a2a_agent(agent_url, agent_name)
        results.append(result)
        print()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    successful = sum(results)
    total = len(results)
    print(f"Agents Online: {successful}/{total}")
    
    if successful == total:
        print("\n✅ All agents are online and ready!")
        return 0
    else:
        print("\n❌ Some agents are offline. Please check A2A server.")
        print("\nTo start the A2A server:")
        print("  python scripts/start_a2a_server.py")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

