"""Tests for bot/composio.py — schema conversion and response digging. Composio itself is faked."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from bot.composio import declarations_for, execute_tool, find_key, gemini_schema, run_action


def test_gemini_schema_keeps_only_supported_keys_recursively():
    schema = {
        "title": "Params",
        "type": "object",
        "properties": {
            "summary": {"type": "string", "title": "Summary", "default": "", "examples": ["x"]},
            "attendees": {"type": "array", "items": {"type": "string", "title": "Email"}},
            "when": {"type": ["string", "null"], "description": "ISO time"},
            "nested": {"properties": {"a": {"type": "integer"}}, "$defs": {}},
        },
        "required": ["summary"],
        "$defs": {"Thing": {}},
    }
    assert gemini_schema(schema) == {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "attendees": {"type": "array", "items": {"type": "string"}},
            "when": {"type": "string", "nullable": True, "description": "ISO time"},
            "nested": {"type": "object", "properties": {"a": {"type": "integer"}}},
        },
        "required": ["summary"],
    }


def fake_toolset(models=None, error=None):
    toolset = Mock()
    if error:
        toolset.get_action_schemas.side_effect = error
    else:
        toolset.get_action_schemas.return_value = models or []
    return toolset


def model(name, **props):
    params = SimpleNamespace(
        model_dump=lambda exclude_none=True: {"type": "object", "properties": props, "title": "P"}
    )
    return SimpleNamespace(name=name, description=f"{name} desc", parameters=params)


def test_declarations_for_converts_models_and_skips_unknown_actions(caplog):
    toolset = fake_toolset([model("NOTION_SEARCH_NOTION_PAGE", query={"type": "string", "title": "Q"})])
    decls = declarations_for(toolset, ("NOTION_SEARCH_NOTION_PAGE", "NOTION_NOT_A_THING"))
    toolset.get_action_schemas.assert_called_once_with(
        actions=["NOTION_SEARCH_NOTION_PAGE", "NOTION_NOT_A_THING"], check_connected_accounts=False
    )
    assert [d.name for d in decls] == ["NOTION_SEARCH_NOTION_PAGE"]
    assert decls[0].parameters.properties["query"].type.name == "STRING"
    assert "composio_action_unknown action=NOTION_NOT_A_THING" in caplog.text


def test_declarations_for_survives_composio_being_down(caplog):
    assert declarations_for(fake_toolset(error=RuntimeError("down")), ("X",)) == []
    assert "composio_schemas_failed" in caplog.text
    assert declarations_for(fake_toolset(), ()) == []  # nothing requested → no call


def test_execute_tool_wraps_success_and_failure():
    toolset = Mock()
    toolset.execute_action.return_value = {"id": "1"}
    assert execute_tool(toolset, "A", {"x": 1}, "dobby") == {"success": True, "data": {"id": "1"}}
    toolset.execute_action.assert_called_once_with(action="A", params={"x": 1}, entity_id="dobby")
    toolset.execute_action.side_effect = RuntimeError("nope")
    assert execute_tool(toolset, "A", {}, "dobby") == {"success": False, "error": "nope"}


def test_run_action_runs_off_the_event_loop():
    toolset = Mock()
    toolset.execute_action.return_value = "ok"
    assert asyncio.run(run_action(toolset, "A", {}, "dobby")) == {"success": True, "data": "ok"}


def test_find_key_digs_through_envelopes():
    data = {"response_data": {"data": [{"id": "", "creation_id": "17"}]}, "successful": True}
    assert find_key(data, "id", "creation_id") == "17"
    assert find_key(data, "missing") is None
    assert find_key([{"sub": "abc"}], "sub") == "abc"
