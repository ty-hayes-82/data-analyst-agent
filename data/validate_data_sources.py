"""End-to-end validation of all data sources with sample queries."""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pl_analyst_agent.config import config


async def fetch_sample_data(agent_url: str, agent_name: str, sample_query: str) -> dict:
    """Fetch sample data from an A2A agent."""
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Send query to agent
            response = await client.post(
                f"{agent_url}/query",
                json={"query": sample_query}
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "agent": agent_name,
                    "data": data
                }
            else:
                return {
                    "success": False,
                    "agent": agent_name,
                    "error": f"HTTP {response.status_code}"
                }
                
    except Exception as e:
        return {
            "success": False,
            "agent": agent_name,
            "error": str(e)
        }


async def validate_pl_data():
    """Validate P&L data source."""
    print("\n" + "=" * 60)
    print("1. Validating P&L Data (Account Research)")
    print("=" * 60)
    
    # Calculate date range (last 30 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    query = f"""
    Fetch P&L data for the last 30 days.
    Start date: {start_date.strftime('%Y-%m-%d')}
    End date: {end_date.strftime('%Y-%m-%d')}
    """
    
    agent_url = f"{config.a2a_base_url}/tableau_account_research_ds_agent"
    result = await fetch_sample_data(agent_url, "Account Research", query)
    
    if result["success"]:
        print("✅ P&L data fetch successful")
        # Note: Actual data structure depends on agent implementation
        print("   Data received from agent")
        return True
    else:
        print(f"❌ P&L data fetch failed: {result.get('error', 'Unknown error')}")
        return False


async def validate_ops_metrics():
    """Validate ops metrics data source."""
    print("\n" + "=" * 60)
    print("2. Validating Ops Metrics")
    print("=" * 60)
    
    # Calculate date range (last 30 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    query = f"""
    Fetch operational metrics for the last 30 days.
    Start date: {start_date.strftime('%Y-%m-%d')}
    End date: {end_date.strftime('%Y-%m-%d')}
    """
    
    agent_url = f"{config.a2a_base_url}/tableau_ops_metrics_ds_agent"
    result = await fetch_sample_data(agent_url, "Ops Metrics", query)
    
    if result["success"]:
        print("✅ Ops metrics fetch successful")
        print("   Data received from agent")
        return True
    else:
        print(f"❌ Ops metrics fetch failed: {result.get('error', 'Unknown error')}")
        return False


async def validate_order_details():
    """Validate order details data source."""
    print("\n" + "=" * 60)
    print("3. Validating Order Details")
    print("=" * 60)
    
    # Calculate date range (last 7 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    query = f"""
    Fetch order details for the last 7 days.
    Start date: {start_date.strftime('%Y-%m-%d')}
    End date: {end_date.strftime('%Y-%m-%d')}
    """
    
    agent_url = f"{config.a2a_base_url}/tableau_order_dispatch_revenue_ds_agent"
    result = await fetch_sample_data(agent_url, "Order Details", query)
    
    if result["success"]:
        print("✅ Order details fetch successful")
        print("   Data received from agent")
        return True
    else:
        print(f"❌ Order details fetch failed: {result.get('error', 'Unknown error')}")
        return False


async def main():
    """Run all data source validations."""
    print("=" * 60)
    print("P&L Analyst - Data Source Validation")
    print("=" * 60)
    print(f"\nA2A Base URL: {config.a2a_base_url}")
    print(f"Testing with sample queries...\n")
    
    # Run validations
    results = []
    results.append(await validate_pl_data())
    results.append(await validate_ops_metrics())
    results.append(await validate_order_details())
    
    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    successful = sum(results)
    total = len(results)
    print(f"Data Sources Valid: {successful}/{total}")
    
    if successful == total:
        print("\n✅ All data sources validated successfully!")
        print("\nThe P&L Analyst Agent is ready to use.")
        return 0
    else:
        print("\n❌ Some data sources failed validation.")
        print("\nTroubleshooting:")
        print("1. Ensure A2A server is running: python scripts/start_a2a_server.py")
        print("2. Check database connectivity: python data/test_database_connection.py")
        print("3. Verify service account credentials exist")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

