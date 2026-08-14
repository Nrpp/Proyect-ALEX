"""
Central error hierarchy for ALEX.

Every subsystem raises one of these instead of bare exceptions, so the Core
and the API layer can catch `AlexError` and always produce a safe, consistent
response instead of leaking stack traces to clients or crashing the process.
"""
from __future__ import annotations


class AlexError(Exception):
    """Base class for every error raised inside ALEX."""

    def __init__(self, message: str, *, code: str = "internal_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class ConfigError(AlexError):
    def __init__(self, message: str):
        super().__init__(message, code="config_error")


class MemoryError_(AlexError):
    """Named with a trailing underscore to avoid shadowing the builtin MemoryError."""

    def __init__(self, message: str):
        super().__init__(message, code="memory_error")


class AIProviderError(AlexError):
    def __init__(self, message: str):
        super().__init__(message, code="ai_provider_error")


class ToolError(AlexError):
    def __init__(self, message: str):
        super().__init__(message, code="tool_error")


class PermissionDenied(AlexError):
    """Raised when the Permission Manager blocks or refuses a tool call."""

    def __init__(self, message: str):
        super().__init__(message, code="permission_denied")


class ConfirmationRequired(AlexError):
    """
    Raised (and caught by the Core) when a tool needs explicit user confirmation
    before it can run. Carries the pending action id so the caller can surface
    it to the user instead of treating it as a failure.
    """

    def __init__(self, message: str, action_id: str):
        super().__init__(message, code="confirmation_required")
        self.action_id = action_id


class PluginError(AlexError):
    def __init__(self, message: str):
        super().__init__(message, code="plugin_error")


class VoiceError(AlexError):
    def __init__(self, message: str):
        super().__init__(message, code="voice_error")
