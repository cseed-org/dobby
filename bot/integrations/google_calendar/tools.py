"""Local tools: things the calendar needs that never go through Composio."""

from bot.AIModels import FunctionDeclaration

from ...memory import find_user_by_name
from ..base import LocalTool, RunContext


async def lookup_calendar_email(ctx: RunContext, params: dict) -> dict:
    name = params.get("name", "")
    user = await find_user_by_name(ctx.session, name)
    if user is None:
        return {"success": True, "found": False, "name": name}
    return {
        "success": True,
        "found": True,
        "display_name": user["display_name"],
        "email": user["calendar_email"],
    }


LOOKUP_TOOL = LocalTool(
    declaration=FunctionDeclaration(
        name="lookup_calendar_email",
        description=(
            "Find a server member's calendar email by their name so they can be invited to an event. "
            "Returns the matched display name and email, or found=false."
        ),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "The person's name as written"}},
            "required": ["name"],
        },
    ),
    handler=lookup_calendar_email,
)
