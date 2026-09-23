import os
from unittest.mock import patch

import pytest

from bot.config import Config


@pytest.mark.parametrize(
    "value,expected", [(None, "gemini-3.1-flash-lite"), (" custom ", "custom"), ("", "")]
)
def test_backup_model_configuration(value, expected):
    env = {
        "DOBBY_ENV_FILE": "/nonexistent.env",
        "DISCORD_TOKEN": "test",
        "DISCORD_GUILD_ID": "1",
        "ALLOWED_USER_IDS": "1",
        "GEMINI_API_KEY": "test",
        "COMPOSIO_API_KEY": "test",
        "DATABASE_URL": "test",
    }
    if value is not None:
        env["GEMINI_MODEL_BACKUP"] = value
    with patch.dict(os.environ, env, clear=True):
        assert Config.load().model_backup == expected
