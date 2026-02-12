"""Test direct SQL Server database connectivity."""

import sys
from pathlib import Path
import yaml

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_database_connection():
    """Test SQL Server database connectivity."""
    print("=" * 60)
    print("P&L Analyst - Database Connection Test")
    print("=" * 60)
    
    # Load database config
    config_file = project_root / "database_config.yaml"
    if not config_file.exists():
        print(f"\n❌ Database config not found: {config_file}")
        print("\nPlease create database_config.yaml with your database credentials.")
        print("See config/database_config.yaml.example for template.")
        return 1
    
    try:
        with open(config_file, 'r') as f:
            db_config = yaml.safe_load(f)
        print("\n✅ Database config loaded")
        print(f"   Server: {db_config.get('server', 'N/A')}")
        print(f"   Database: {db_config.get('database', 'N/A')}")
        print(f"   Driver: {db_config.get('driver', 'N/A')}")
    except Exception as e:
        print(f"\n❌ Failed to load database config: {e}")
        return 1
    
    # Test pyodbc import
    try:
        import pyodbc
        print("\n✅ pyodbc module available")
    except ImportError:
        print("\n❌ pyodbc not installed")
        print("   Install with: pip install pyodbc")
        return 1
    
    # Build connection string
    try:
        conn_string = (
            f"DRIVER={db_config['driver']};"
            f"SERVER={db_config['server']};"
            f"DATABASE={db_config['database']};"
            f"UID={db_config['username']};"
            f"PWD={db_config['password']}"
        )
        print("\n✅ Connection string built")
    except KeyError as e:
        print(f"\n❌ Missing required config key: {e}")
        return 1
    
    # Test connection
    try:
        print("\n⏳ Connecting to database...")
        conn = pyodbc.connect(conn_string, timeout=30)
        print("✅ Database connection successful!")
        
        # Test query
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        print(f"\n✅ Query test successful")
        print(f"   SQL Server Version: {version[:50]}...")
        
        cursor.close()
        conn.close()
        print("\n✅ Connection closed cleanly")
        
        print("\n" + "=" * 60)
        print("DATABASE TEST PASSED")
        print("=" * 60)
        return 0
        
    except pyodbc.Error as e:
        print(f"\n❌ Database connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Verify database credentials in database_config.yaml")
        print("2. Check network connectivity to SQL Server")
        print("3. Ensure firewall allows connection")
        print("4. Verify ODBC Driver 17 is installed")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(test_database_connection())

