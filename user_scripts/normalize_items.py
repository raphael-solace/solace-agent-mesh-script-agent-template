from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from sam_script_agent.runtime import ScriptAgentResult


def _normalize_items(values: List[Any]) -> List[str]:
    return [str(value).strip().lower() for value in values if str(value).strip()]


def _extract_json_payload(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None

    candidates = [stripped]
    for match in re.finditer(r"(\[[\s\S]*\]|\{[\s\S]*\})", stripped):
        candidates.append(match.group(1))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


async def run(
    items: Optional[List[str]] = None,
    item: Optional[str] = None,
    text: Optional[str] = None,
    operation: str = "normalize",
    context=None,
    **_: Dict[str, Any],
) -> ScriptAgentResult:
    if context is not None and hasattr(context, "emit_progress"):
        await context.emit_progress("Normalizing item payload")

    if items is None and item is None and text:
        parsed = _extract_json_payload(text)
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            items = parsed.get("items")
            item = parsed.get("item")
            operation = parsed.get("operation", operation)
        else:
            stripped = text.strip()
            lowered = stripped.lower()
            if "uppercase" in lowered:
                operation = "uppercase"
            elif "length" in lowered:
                operation = "length"

            lines = [line.strip() for line in stripped.splitlines() if line.strip()]
            if len(lines) >= 2 and lines[0].lower() in {"uppercase", "length", "normalize"}:
                operation = lines[0].lower()
                item = lines[1]
            elif len(lines) == 1:
                if ":" in lines[0]:
                    prefix, value = lines[0].split(":", 1)
                    prefix_lower = prefix.lower()
                    if "uppercase" in prefix_lower:
                        operation = "uppercase"
                        item = value.strip()
                    elif "length" in prefix_lower:
                        operation = "length"
                        item = value.strip()
                    else:
                        item = lines[0]
                else:
                    item = lines[0]
            elif lines:
                items = lines

    if items is not None:
        processed = _normalize_items(items)
        return ScriptAgentResult(
            text=f"Processed {len(processed)} items.",
            data={"processed_items": processed, "count": len(processed)},
        )

    if item is not None:
        if operation == "uppercase":
            transformed = item.upper()
        elif operation == "length":
            transformed = len(item)
        else:
            transformed = item.strip().lower()
        return ScriptAgentResult(
            text=f"Item processed with operation '{operation}'.",
            data={"processed_item": transformed, "operation": operation},
        )

    return ScriptAgentResult(
        text="No items were provided.",
        data={"processed_items": [], "count": 0},
    )
