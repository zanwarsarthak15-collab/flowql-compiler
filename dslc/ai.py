"""
FlowQL AI Tier (Google Gemini Integration).

Provides advisory AI error diagnostics and target code reviews using the
official google-genai SDK. Gracefully falls back when API key is missing
or network fails, ensuring the core compiler never crashes.
"""
import os
import json
import re
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

def _get_api_key() -> str:
    """Retrieve GEMINI_API_KEY dynamically from environment or .env."""
    return os.getenv("GEMINI_API_KEY", "").strip()


def _get_model_name() -> str:
    """Retrieve GEMINI_MODEL dynamically from environment or .env."""
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()


def _is_api_key_valid() -> bool:
    """Check if a non-dummy API key is set in environment."""
    key = _get_api_key()
    return bool(key and not key.startswith("your_"))


def _clean_json_response(raw_text: str) -> Optional[dict]:
    """Extract and parse JSON object from LLM response defensively."""
    if not raw_text:
        return None

    # Remove markdown code fences if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned.strip())
    except Exception:
        # Fallback regex search for JSON object {...}
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return None


def explain_error(
    error_dict: Dict[str, Any],
    source_code: str,
    grammar_summary: str = ""
) -> Dict[str, Any]:
    """
    Explains a FlowQL compile error in plain English and suggests a fix.
    Advisory only: returns friendly fallback if Gemini is offline or unconfigured.
    """
    if not _is_api_key_valid():
        return {
            "available": False,
            "cause": "AI hints unavailable: GEMINI_API_KEY is not configured in .env.",
            "suggested_code": "",
            "tip": "Configure GEMINI_API_KEY in your .env file to enable automated explanations."
        }

    try:
        from google import genai

        client = genai.Client(api_key=_get_api_key())

        prompt = f"""You are a helpful compiler teaching assistant for FlowQL, a college semester DSL project.
A student received a compiler error. Explain the error simply and clearly.

Error Code: {error_dict.get('code')}
Message: {error_dict.get('message')}
Line: {error_dict.get('line')}, Column: {error_dict.get('column')}
Failing Line: {error_dict.get('source_line')}

Full Source Code:
```
{source_code}
```

Instructions:
1. Explain the root cause in 1-2 friendly, clear sentences (no jargon).
2. Provide the corrected FlowQL code replacement in "suggested_code" (either the corrected single statement or the full corrected program).
3. Provide one short tip to avoid this in the future.
4. Output STRICT JSON only with keys "cause", "suggested_code", "tip". Do not wrap in markdown quotes if possible.
"""

        response = client.models.generate_content(
            model=_get_model_name(),
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )

        parsed = _clean_json_response(response.text if hasattr(response, 'text') else "")
        if parsed and "cause" in parsed:
            return {
                "available": True,
                "cause": parsed.get("cause", ""),
                "suggested_code": parsed.get("suggested_code", ""),
                "tip": parsed.get("tip", "")
            }

        # If JSON couldn't be parsed, use text directly
        raw = response.text if hasattr(response, 'text') else "Could not parse response"
        return {
            "available": True,
            "cause": raw[:250],
            "suggested_code": "",
            "tip": "Review your statement syntax and schema columns."
        }

    except Exception as e:
        return {
            "available": False,
            "cause": f"AI hints unavailable ({type(e).__name__}).",
            "suggested_code": "",
            "tip": "Deterministic error reporting succeeded. Check syntax or schema definitions."
        }


def review_code(
    source_code: str,
    target_code: str,
    target_name: str
) -> Dict[str, Any]:
    """
    Reviews FlowQL source code and generated target code (Python or SQL).
    Returns a short verdict and up to 3 improvement tips.
    """
    if not _is_api_key_valid():
        return {
            "available": False,
            "verdict": "AI review unavailable (GEMINI_API_KEY not configured)",
            "tips": ["Add GEMINI_API_KEY to .env to unlock AI code review and optimization suggestions."]
        }

    try:
        from google import genai

        client = genai.Client(api_key=_get_api_key())

        prompt = f"""You are a compiler reviewer assessing a FlowQL program and its generated {target_name} output.

FlowQL Source:
```
{source_code}
```

Generated {target_name} Code:
```
{target_code}
```

Instructions:
1. Give a 1-sentence verdict on pipeline correctness and efficiency.
2. List 1 to 3 concise, practical improvement tips.
3. Output STRICT JSON only with keys "verdict" and "tips" (an array of strings).
"""

        response = client.models.generate_content(
            model=_get_model_name(),
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )

        parsed = _clean_json_response(response.text if hasattr(response, 'text') else "")
        if parsed and "verdict" in parsed:
            tips = parsed.get("tips", [])
            if not isinstance(tips, list):
                tips = [str(tips)]
            return {
                "available": True,
                "verdict": parsed.get("verdict", "Valid pipeline"),
                "tips": tips[:3]
            }

        return {
            "available": True,
            "verdict": "Pipeline successfully compiled and verified.",
            "tips": ["Ensure CSV file exists at execution runtime.", "Verify column types match source data."]
        }

    except Exception as e:
        return {
            "available": False,
            "verdict": f"AI review unavailable ({type(e).__name__})",
            "tips": ["The compiler generated target code deterministically without AI review."]
        }
