"""Composio bridge: curated action schemas → Gemini declarations, and execution under the service entity.

Uses the current ``composio`` SDK's raw schemas and direct execution API, preserving Dobby's
curated tool allowlist and local confirmation gate without a framework adapter.
"""

import asyncio
import logging

from composio import Composio
from google.genai import types

log = logging.getLogger("composio")

# The subset of JSON Schema that Gemini function declarations accept.
SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "nullable"}

# Required, not just tidiness: `tools.execute` raises ToolVersionRequiredError when a toolkit
# resolves to "latest", which is the default. Pinning also keeps schemas and execution on the
# same catalog release. Re-check against docs.composio.dev/toolkits/<slug> when updating tools;
# a stale pin surfaces as `composio_schemas_failed` at startup and no declarations.
TOOLKIT_VERSIONS = dict.fromkeys(("googlecalendar", "notion", "instagram", "linkedin"), "20260915_00")


def get_toolset(api_key: str) -> Composio:
    return Composio(api_key=api_key, toolkit_versions=TOOLKIT_VERSIONS)


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


def declarations_for(toolset: Composio, actions: tuple[str, ...]) -> list[types.FunctionDeclaration]:
    """Gemini declarations for the named Composio actions. Unknown actions are logged and skipped."""
    if not actions:
        return []
    try:
        models = toolset.tools.get_raw_composio_tools(tools=list(actions))
    except Exception as exc:
        log.error("composio_schemas_failed actions=%s type=%s", ",".join(actions), type(exc).__name__)
        return []
    declarations = []
    seen = set()
    for model in models:
        params = model.input_parameters
        if hasattr(params, "model_dump"):
            params = params.model_dump(exclude_none=True)
        schema = gemini_schema(params or {})
        declarations.append(
            types.FunctionDeclaration(
                name=model.slug,
                description=model.description or "",
                parameters=schema or None,
            )
        )
        seen.add(model.slug)
    for name in actions:
        if name not in seen:
            log.warning("composio_action_unknown action=%s", name)
    return declarations


def execute_tool(toolset: Composio, tool_name: str, params: dict, entity_id: str) -> dict:
    try:
        result = toolset.tools.execute(slug=tool_name, arguments=params, user_id=entity_id)
        if not result.get("successful"):
            return {"success": False, "error": result.get("error") or "Composio tool execution failed"}
        return {"success": True, "data": result.get("data")}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def run_action(toolset: Composio, tool_name: str, params: dict, entity_id: str) -> dict:
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
