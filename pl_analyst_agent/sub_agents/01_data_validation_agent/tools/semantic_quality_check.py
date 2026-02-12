import json
import pandas as pd
from io import StringIO
from ....semantic.quality import DataQualityGate
from ....semantic.models import DatasetContract

async def semantic_quality_check(data_csv: str, contract_name: str = "pl_contract") -> str:
    """
    Validates data against its semantic DatasetContract.
    
    Args:
        data_csv: The CSV data as a string.
        contract_name: The name of the contract to use (default: pl_contract).
        
    Returns:
        JSON string containing the QualityReport.
    """
    try:
        # 1. Load the contract (In a real scenario, we might get this from state, 
        # but for a tool call we load it from disk or use a cached version)
        # Note: In ADK tools, accessing session state directly is not standard,
        # but the agent can pass it.
        
        import os
        from pathlib import Path
        
        project_root = Path(__file__).parent.parent.parent.parent.parent
        contract_path = project_root / "contracts" / f"{contract_name}.yaml"
        
        if not contract_path.exists():
            return json.dumps({"error": f"Contract {contract_name} not found at {contract_path}"})
            
        contract = DatasetContract.from_yaml(str(contract_path))
        
        # 2. Load data
        df = pd.read_csv(StringIO(data_csv))
        
        # 3. Validate
        gate = DataQualityGate(contract)
        report = gate.validate(df)
        
        return report.model_dump_json(indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": "QualityGateError",
            "detail": str(e)
        })
