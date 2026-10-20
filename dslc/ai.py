"""
FlowQL AI Tier (Google Gemini Integration).

Provides advisory AI error diagnostics and target code reviews using the
official google-genai SDK. Gracefully falls back when API key is missing
or network fails, ensuring the core compiler never crashes.
"""
import os
import json
import re
from typing import Dict, Any, Optional, List
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


import time
import concurrent.futures

# Default timeout in seconds for Gemini API calls
GEMINI_TIMEOUT_SECONDS = 8.0


def _call_gemini_with_retry(prompt: str, timeout_seconds: float = GEMINI_TIMEOUT_SECONDS, max_retries: int = 1) -> Optional[str]:
    """
    Executes a Gemini API request with strict timeout and 1 automatic retry on temporary failures.
    Returns the response text or raises an exception.
    """
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    model_name = _get_model_name()

    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                response = future.result(timeout=timeout_seconds)
                return response.text if hasattr(response, "text") else ""
        except concurrent.futures.TimeoutError:
            last_exception = TimeoutError(f"Gemini API timed out after {timeout_seconds}s")
            if attempt < max_retries:
                time.sleep(0.5)
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                time.sleep(0.5)

    if last_exception:
        raise last_exception
    return None


def explain_error(
    error_dict: Dict[str, Any],
    source_code: str,
    schema_info: Optional[List[Dict[str, Any]]] = None,
    sample_rows: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Explains a FlowQL compile error in plain English and suggests a fix.
    Advisory only: returns friendly fallback if Gemini is offline or unconfigured.
    Sends only minimal context: error, bounded source code, schema, and max 5 sample rows.
    """
    if not _is_api_key_valid():
        return {
            "available": False,
            "cause": "AI hints unavailable: GEMINI_API_KEY is not configured in .env.",
            "suggested_code": "",
            "tip": "Configure GEMINI_API_KEY in your .env file to enable automated explanations."
        }

    try:
        # Bound source code size to avoid unnecessary token usage
        bounded_source = source_code[:1200] if source_code else ""

        # Build concise schema and sample context (at most 5 sample rows, never whole dataset)
        schema_summary = ""
        if schema_info:
            cols_str = ", ".join([f"{c.get('name')}: {c.get('type')}" for c in schema_info[:15]])
            schema_summary = f"\nDataset Columns: {cols_str}"

        sample_summary = ""
        if sample_rows:
            sample_summary = f"\nSample Data (first {min(len(sample_rows), 5)} rows): {json.dumps(sample_rows[:5])}"

        prompt = f"""You are a helpful compiler teaching assistant for FlowQL, a college semester DSL project.
A student received a compiler error. Explain the error simply and clearly.

Error Code: {error_dict.get('code')}
Message: {error_dict.get('message')}
Line: {error_dict.get('line')}, Column: {error_dict.get('column')}
Failing Line: {error_dict.get('source_line')}{schema_summary}{sample_summary}

Full Source Code:
```
{bounded_source}
```

Instructions:
1. Explain the root cause in 1-2 friendly, clear sentences (no jargon).
2. Provide the corrected FlowQL code replacement in "suggested_code" (either the corrected single statement or the full corrected program).
3. Provide one short tip to avoid this in the future.
4. Output STRICT JSON only with keys "cause", "suggested_code", "tip".
"""

        raw_text = _call_gemini_with_retry(prompt, timeout_seconds=GEMINI_TIMEOUT_SECONDS, max_retries=1)
        parsed = _clean_json_response(raw_text or "")

        if parsed and isinstance(parsed, dict) and "cause" in parsed:
            cause_text = str(parsed.get("cause", "")).strip()
            suggested = str(parsed.get("suggested_code", "")).strip()
            tip_text = str(parsed.get("tip", "")).strip()
            if cause_text:
                return {
                    "available": True,
                    "cause": cause_text,
                    "suggested_code": suggested,
                    "tip": tip_text or "Check syntax and declared schema column names."
                }

        # Fallback if JSON format was incomplete
        return {
            "available": True,
            "cause": "Review statement syntax and column types in the pipeline.",
            "suggested_code": "",
            "tip": "Check your FlowQL dataset schema and expression types."
        }

    except TimeoutError:
        return {
            "available": False,
            "cause": "AI hints timed out. The compiler verified your code deterministically.",
            "suggested_code": "",
            "tip": "Review line diagnostics on the left to locate syntax issues."
        }
    except Exception as e:
        return {
            "available": False,
            "cause": f"AI hints unavailable ({type(e).__name__}).",
            "suggested_code": "",
            "tip": "Deterministic compiler diagnostics succeeded. Check syntax or schema definitions."
        }


def review_code(
    source_code: str,
    target_code: str,
    target_name: str
) -> Dict[str, Any]:
    """
    Reviews FlowQL source code and generated target code (Python or SQL).
    Returns a short verdict and up to 3 improvement tips.
    Enforces strict timeout, 1 retry, and strict JSON output validation.
    """
    if not _is_api_key_valid():
        return {
            "available": False,
            "verdict": "AI review unavailable (GEMINI_API_KEY not configured)",
            "tips": ["Add GEMINI_API_KEY to .env to unlock AI code review and optimization suggestions."]
        }

    try:
        # Bound prompt size to prevent sending huge texts
        bounded_source = source_code[:1200] if source_code else ""
        bounded_target = target_code[:1500] if target_code else ""

        prompt = f"""You are a compiler reviewer assessing a FlowQL program and its generated {target_name} output.

FlowQL Source:
```
{bounded_source}
```

Generated {target_name} Code:
```
{bounded_target}
```

Instructions:
1. Give a 1-sentence verdict on pipeline correctness and efficiency.
2. List 1 to 3 concise, practical improvement tips.
3. Output STRICT JSON only with keys "verdict" and "tips" (an array of strings).
"""

        raw_text = _call_gemini_with_retry(prompt, timeout_seconds=GEMINI_TIMEOUT_SECONDS, max_retries=1)
        parsed = _clean_json_response(raw_text or "")

        if parsed and isinstance(parsed, dict) and "verdict" in parsed:
            verdict = str(parsed.get("verdict", "")).strip()
            tips = parsed.get("tips", [])
            if not isinstance(tips, list):
                tips = [str(tips)]
            clean_tips = [str(t).strip() for t in tips if str(t).strip()][:3]
            return {
                "available": True,
                "verdict": verdict or "Pipeline successfully compiled and verified.",
                "tips": clean_tips or ["Verify dataset path and column names before execution."]
            }

        return {
            "available": True,
            "verdict": "Pipeline successfully compiled and verified.",
            "tips": ["Ensure CSV file exists at execution runtime.", "Verify column types match source data."]
        }

    except TimeoutError:
        return {
            "available": False,
            "verdict": "AI review timed out. Target code was generated deterministically.",
            "tips": ["The compiler generated target code successfully without AI review."]
        }
    except Exception as e:
        return {
            "available": False,
            "verdict": f"AI review unavailable ({type(e).__name__})",
            "tips": ["The compiler generated target code deterministically without AI review."]
        }

