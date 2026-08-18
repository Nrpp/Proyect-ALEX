from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from alex.plugins.installed.email_plugin import EmailSendTool
from alex.tools.base import PermissionLevel

pytestmark = pytest.mark.asyncio


async def _run_blocking(fn, *args):
    return fn(*args)


async def test_tool_is_confirm_gated():
    tool = EmailSendTool("alex@gmail.com", "app-pass", _run_blocking)
    assert tool.permission_level == PermissionLevel.CONFIRM


async def test_send_logs_in_and_sends_via_smtp_ssl():
    tool = EmailSendTool("alex@gmail.com", "app-pass", _run_blocking)
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn

    with patch("smtplib.SMTP_SSL", return_value=mock_conn) as mock_smtp:
        result = await tool.run(to="friend@example.com", subject="Hola", body="Que tal")

    assert result.success is True
    assert "friend@example.com" in result.content
    mock_smtp.assert_called_once_with("smtp.gmail.com", 465, timeout=15)
    mock_conn.login.assert_called_once_with("alex@gmail.com", "app-pass")
    assert mock_conn.sendmail.call_count == 1
    from_addr, to_addrs, raw_message = mock_conn.sendmail.call_args.args
    assert from_addr == "alex@gmail.com"
    assert to_addrs == ["friend@example.com"]
    assert "Hola" in raw_message
    assert "Que tal" in raw_message
