import json
import re
from typing import Any, Dict

def safe_parse_json(value: Any) -> Dict[str, Any]:
    """
    Safely parses a value that could be a dict or a markdown-wrapped JSON string.
    
    Args:
        value: The value to parse (dict or string).
        
    Returns:
        A dictionary representation of the JSON data. Returns empty dict on failure.
    """
    if isinstance(value, dict):
        return value
    
    if not isinstance(value, str) or not value.strip():
        return {}
    
    try:
        # 1. Try direct parse
        return json.loads(value)
    except json.JSONDecodeError:
        try:
            # 2. Try cleaning markdown blocks
            clean_json = re.sub(r'^```(?:json)?\s*|\s*```$', '', value.strip(), flags=re.MULTILINE | re.IGNORECASE)
            return json.loads(clean_json)
        except Exception:
            # 3. Last ditch: try finding anything that looks like {...}
            try:
                match = re.search(r'(\{.*\})', value, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
            except Exception:
                pass
    
    return {}
