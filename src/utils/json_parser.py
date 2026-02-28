import json
import re
import ast
from typing import Optional, Any

def robust_parse_json(text: str, expect_array: bool = False) -> Optional[Any]:
    """
    Robustly parse JSON strings returned by LLMs.
    Handles markdown blocks, prefix/suffix text, and uses AST as a final fallback.
    """
    if not text:
        return None
        
    # 1. Direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
        
    # 2. Strip markdown blocks
    clean_text = re.sub(r'```(?:json)?', '', text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(clean_text)
    except Exception:
        pass
        
    # 3. Regex extraction
    pattern = r'\[.*\]' if expect_array else r'\{.*\}'
    match = re.search(pattern, clean_text, re.DOTALL)
    if match:
        extracted = match.group()
        try:
            return json.loads(extracted)
        except Exception:
            pass
            
        # 4. AST Literal Eval Fallback (handles trailing commas, unquoted keys sometimes, etc.)
        try:
            # Replace JSON boolean/null with Python equivalents
            ast_str = extracted.replace("true", "True").replace("false", "False").replace("null", "None")
            parsed = ast.literal_eval(ast_str)
            if isinstance(parsed, list) if expect_array else isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
            
    return None
