"""Composio bridge: curated action schemas → Gemini declarations, and execution under the service entity.

Uses the base ``composio-core`` toolset API (``get_action_schemas`` / ``execute_action``); the
framework adapters (``composio_gemini``) are not installed.
"""

import asyncio
import logging

from composio import ComposioToolSet
from google.genai import types

log = logging.getLogger("composio")

# The subset of JSON Schema that Gemini function declarations accept.
SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "nullable"}


def get_toolset(api_key: str) -> ComposioToolSet:
    return ComposioToolSet(api_key=api_key)


def gemini_schema(schema: dict) -> dict:
    """Strip a Composio parameter schema down to what Gemini accepts (no title/default/examples/$defs)."""
    out = {}
    for key, value in schema.items():
        if key not in SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: gemini_schema(prop) for name, prop in value.items() if isinstance(prop, dict)}
        elif key == "items" and isinstance(value, dict):
            out[key] = gemini_schema(value)
        elif key == "type" and isinstance(value, list):
            # ["string", "null"] → string + nullable
            kinds = [v for v in value if v != "null"]
            if kinds:
                out["type"] = kinds[0]
            if len(kinds) < len(value):
                out["nullable"] = True
        else:
            out[key] = value
    if "properties" in out and "type" not in out:
        out["type"] = "object"
    return out


def declarations_for(toolset: ComposioToolSet, actions: tuple[str, ...]) -> list[types.FunctionDeclaration]:
    """Gemini declarations for the named Composio actions. Unknown actions are logged and skipped."""
    if not actions:
        return []
    try:
        models = toolset.get_action_schemas(actions=list(actions), check_connected_accounts=False)
    except Exception as exc:
        log.error("composio_schemas_failed actions=%s type=%s", ",".join(actions), type(exc).__name__)
        return []
    declarations = []
    seen = set()
    for model in models:
        params = model.parameters
        if hasattr(params, "model_dump"):
            params = params.model_dump(exclude_none=True)
        schema = gemini_schema(params or {})
        declarations.append(
            types.FunctionDeclaration(
                name=model.name,
                description=model.description or "",
                parameters=schema or None,
            )
        )
        seen.add(model.name)
    for name in actions:
        if name not in seen:
            log.warning("composio_action_unknown action=%s", name)
    return declarations


def execute_tool(toolset: ComposioToolSet, tool_name: str, params: dict, entity_id: str) -> dict:
    try:
        result = toolset.execute_action(action=tool_name, params=params, entity_id=entity_id)
        return {"success": True, "data": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def run_action(toolset: ComposioToolSet, tool_name: str, params: dict, entity_id: str) -> dict:
    """`execute_tool` off the event loop; Composio's client is synchronous HTTP."""
    return await asyncio.to_thread(execute_tool, toolset, tool_name, params, entity_id)


def find_key(data, *keys):
    """First value for any of `keys` anywhere in a nested Composio response, or None.

    Composio wraps provider responses in varying envelopes (`data`, `response_data`, ...), so
    callers ask for the field they need rather than a fixed path.
    """
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        for value in data.values():
            found = find_key(value, *keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_key(item, *keys)
            if found is not None:
                return found
    return None
