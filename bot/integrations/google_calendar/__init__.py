"""Google Calendar: the team calendar Dobby creates, moves and deletes events on."""

from ..base import Integration
from . import commands
from .tools import LOOKUP_TOOL

# Curated: what Gemini may call directly. Verified against Composio's catalog at deploy time
# (see docs/BOT_ARCHITECTURE.md → "Adding an integration").
ACTIONS = (
    "GOOGLECALENDAR_CREATE_EVENT",
    "GOOGLECALENDAR_FIND_EVENT",
    "GOOGLECALENDAR_UPDATE_EVENT",
    "GOOGLECALENDAR_DELETE_EVENT",
    "GOOGLECALENDAR_FIND_FREE_SLOTS",
)

PROMPT = (
    "Google Calendar: events go on the team calendar. To invite someone, call "
    "lookup_calendar_email with their name; if it returns no email, say that person has no "
    "calendar email on file. Never guess an address. Default meeting length is one hour."
)

INTEGRATION = Integration(
    key="google_calendar",
    label="Google Calendar",
    app="googlecalendar",
    actions=ACTIONS,
    local_tools=(LOOKUP_TOOL,),
    prompt=PROMPT,
    register_commands=commands.register,
    help_lines=(
        "`/schedule request:Create Project Sync on October 12, 2026 at 10am for 30 minutes`",
        "`/schedule request:Move the design review to October 13 at 2pm`",
        "`/events days:30` → upcoming events",
        "`@Dobby set up a design review Friday at 2pm and invite Maya and @Leonard`",
    ),
)
