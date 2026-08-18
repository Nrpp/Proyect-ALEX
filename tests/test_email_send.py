from __future__ import annotations

import base64
import email
from unittest.mock import AsyncMock

import pytest

from alex.plugins.installed.email_plugin import EmailSendTool, GmailClient
from alex.tools.base import PermissionLevel

pytestmark = pytest.mark.asyncio


async def test_tool_is_confirm_gated():
    client = GmailClient("id", "secret", "refresh", "alex@gmail.com")
    tool = EmailSendTool(client)
    assert tool.permission_level == PermissionLevel.CONFIRM


async def test_send_posts_a_base64url_encoded_rfc822_message():
    client = GmailClient("id", "secret", "refresh", "alex@gmail.com")
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    client._request = AsyncMock(return_value=mock_response)

    tool = EmailSendTool(client)
    result = await tool.run(to="friend@example.com", subject="Hola", body="Que tal")

    assert result.success is True
    assert "friend@example.com" in result.content
    client._request.assert_awaited_once()
    method, path = client._request.await_args.args
    assert method == "POST"
    assert path == "/users/me/messages/send"
    raw = client._request.await_args.kwargs["json"]["raw"]
    decoded = base64.urlsafe_b64decode(raw.encode())
    msg = email.message_from_bytes(decoded)
    assert msg["To"] == "friend@example.com"
    assert msg["Subject"] == "Hola"
    assert msg["From"] == "alex@gmail.com"
    assert msg.get_payload() == "Que tal"
