"""
Central configuration for ALEX.

Everything is loaded from environment variables / a local `.env` file (see
`.env.example`). No secrets ever live in source code. Config is intentionally
a single flat, typed object so every module gets its settings the same way:

    from alex.config import get_settings
    settings = get_settings()
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="ALEX_",
        extra="ignore",
    )

    # --- Identity -----------------------------------------------------
    assistant_name: str = "Alex"
    owner_name: str = "Nicolas"
    timezone: str = "Europe/Madrid"

    # --- Server / API ---------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8787
    # Shared-secret bearer token clients must present. Generate with
    # `python -m alex.scripts.gen_token` or `openssl rand -hex 32`.
    api_token: str = Field(default="")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- Storage --------------------------------------------------------
    data_dir: Path = DATA_DIR
    db_path: Path = DATA_DIR / "alex.db"
    log_dir: Path = DATA_DIR / "logs"
    log_level: str = "INFO"

    # --- AI provider ------------------------------------------------------
    # "nvidia" (NVIDIA NIM, OpenAI-compatible, free tier), "anthropic" (Claude),
    # "openrouter" or "anyapi" (both OpenAI-compatible, many vendors/models
    # behind one key). The rest of ALEX never imports a provider SDK directly
    # - see alex/ai/router.py.
    ai_provider: str = "nvidia"

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.1-70b-instruct"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # A free-tier model by default so this works with zero cost out of the box;
    # change to any model id from https://openrouter.ai/models once you have a
    # preference (paid models need OpenRouter account credits).
    openrouter_model: str = "meta-llama/llama-3.1-8b-instruct:free"

    anyapi_api_key: str = ""
    anyapi_base_url: str = "https://api.anyapi.ai/v1"
    # Model ids are "provider/model-name". Paid models (e.g. "openai/gpt-4o-mini")
    # return 403 key_model_access_denied on a free-credits key, and some models
    # listed under a free key 404 anyway (delisted/unavailable upstream despite
    # still appearing in the catalog - seen in practice with both
    # meta-llama/llama-3.3-70b-instruct:free and qwen/qwen3-coder:free). This
    # default was verified working end-to-end (chat + tool-calling) on a real
    # free account. If it ever stops working, list what your key can actually
    # access and confirm a candidate responds before switching to it:
    #   curl https://api.anyapi.ai/v1/models -H "Authorization: Bearer $ANYAPI_KEY"
    #   curl https://api.anyapi.ai/v1/chat/completions -H "Authorization: Bearer $ANYAPI_KEY" \
    #     -H "Content-Type: application/json" -d '{"model": "<candidate>", "messages": [{"role":"user","content":"hola"}]}'
    anyapi_model: str = "nvidia/nemotron-nano-9b-v2:free"

    ai_max_tokens: int = 1024
    ai_temperature: float = 0.4
    # Safety cap on the tool-calling loop (AI -> tool -> AI -> ...) per turn.
    ai_max_tool_hops: int = 6
    # Per-request timeout for a single call to the AI provider. Without this,
    # a slow/unresponsive provider hangs the whole conversational turn (and
    # the client connection waiting on it) indefinitely.
    ai_request_timeout_seconds: int = 45
    # Timeout for the ENTIRE turn (all AI <-> tool hops combined, up to
    # ai_max_tool_hops). A model that loops through several tool calls
    # without ever finishing could otherwise still hang past
    # ai_request_timeout_seconds even with every individual call bounded.
    ai_turn_timeout_seconds: int = 90

    # --- Memory -----------------------------------------------------------
    memory_recent_messages: int = 20  # short-term context window size
    memory_max_facts_in_prompt: int = 12

    # --- Web Push (optional - notifications on a phone via the installed PWA) --
    # Generate with `python3 scripts/gen_vapid_keys.py`. Leave empty to disable
    # Web Push entirely - the console still works over its WebSocket, this just
    # adds delivery while it's not open (needed for iOS, which has no other way
    # to reach an installed PWA - see clients/web_console/README or docs).
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_contact_email: str = ""

    # --- Plugins ------------------------------------------------------------
    # Add "home_assistant", "email", "google_calendar", "ms_todo" once you've
    # configured their credentials below - not enabled by default since each
    # needs setup outside ALEX first (see docs/INSTALL_RASPBERRY_PI.md).
    enabled_plugins: list[str] = Field(default_factory=lambda: ["system", "reminders", "web", "daily_briefing"])

    # --- Integration: Home Assistant -----------------------------------------
    home_assistant_url: str = ""  # e.g. http://homeassistant.local:8123
    home_assistant_token: str = ""  # long-lived access token from your HA profile page

    # --- Integration: AlexOS --------------------------------------------------
    # The personal-OS dashboard (a separate project). No token needed - its
    # REST API has no authentication of its own (see its docs/ARCHITECTURE.md).
    # Default assumes AlexOS runs on this same Pi via its production
    # docker-compose (network_mode: host, api on port 8000).
    alexos_base_url: str = "http://127.0.0.1:8000"

    # --- Integration: Gmail (Gmail API via OAuth) -----------------------------
    # OAuth2 "installed app" credentials from Google Cloud Console + a refresh
    # token minted once via scripts/google_oauth_auth.py --scopes gmail (run on
    # a machine with a browser, not the Pi). Same client id/secret as Calendar/
    # Tasks works fine if you enable the Gmail API on that same Cloud project.
    gmail_address: str = ""  # used as the From: header on mail ALEX sends
    google_gmail_client_id: str = ""
    google_gmail_client_secret: str = ""
    google_gmail_refresh_token: str = ""
    gmail_check_interval_seconds: int = 300

    # --- Integration: Google Calendar ----------------------------------------
    # OAuth2 "installed app" credentials from Google Cloud Console + a refresh
    # token minted once via scripts/google_oauth_auth.py (run on a machine
    # with a browser, not the Pi).
    google_calendar_client_id: str = ""
    google_calendar_client_secret: str = ""
    google_calendar_refresh_token: str = ""
    google_calendar_id: str = "primary"
    google_calendar_check_interval_seconds: int = 1800

    # --- Integration: Google Tasks -------------------------------------------
    # Independent credentials from Google Calendar by default (can be the
    # same client id/secret/refresh token if minted with both scopes at once
    # via scripts/google_oauth_auth.py --scopes).
    google_tasks_client_id: str = ""
    google_tasks_client_secret: str = ""
    google_tasks_refresh_token: str = ""
    google_tasks_list_id: str = "@default"
    google_tasks_check_interval_seconds: int = 1800

    # --- Integration: Microsoft To Do (Graph API) ----------------------------
    # Public-client Azure AD app id; auth uses the OAuth2 device-code flow
    # (no client secret, no redirect URI needed) - first run prints/notifies
    # a short code to enter at https://microsoft.com/devicelogin.
    ms_client_id: str = ""
    ms_tenant: str = "consumers"  # "consumers" for personal MS accounts, "common" for both
    ms_todo_check_interval_seconds: int = 900

    # --- Tools / permissions ---------------------------------------------------
    # Hard kill-switch: tool names listed here are refused regardless of their
    # declared permission level. Empty by default.
    blocked_tools: list[str] = Field(default_factory=list)

    # --- Voice --------------------------------------------------------------
    voice_enabled: bool = False
    wakeword_model_path: str = ""  # path to .onnx/.tflite model, empty = use openWakeWord default
    wakeword_name: str = "hey_jarvis"  # placeholder default model shipped with openWakeWord
    wakeword_threshold: float = 0.5
    mic_device: str | None = None  # sounddevice device name/index, None = system default
    stt_model_size: str = "small"  # tiny/base/small/medium (faster-whisper)
    stt_language: str = "es"
    tts_voice: str = "es_ES-davefx-medium"  # piper voice model name
    tts_model_dir: Path = DATA_DIR / "voice_models" / "piper"
    conversation_follow_up_seconds: float = 8.0  # window to keep listening w/o wake word

    # --- Notifications --------------------------------------------------------
    notification_min_priority_push: int = 2  # 0=info..3=critical; below this -> log only

    # --- Integration: web browsing --------------------------------------------
    # Timeout for a single page fetch. No API key needed - just reads whatever
    # URL the model is given/finds, same trust model as a person clicking a link.
    web_fetch_timeout_seconds: int = 10

    # --- Daily briefing ---------------------------------------------------------
    # Local HH:MM (in `timezone` above) the proactive morning briefing fires,
    # once per day. News is always included (no credentials needed, see
    # briefing_news_rss_url); today's calendar events and pending tasks are
    # added automatically if google_calendar / google_tasks are configured
    # above, skipped otherwise. Delivered as a normal notification (push/
    # WebSocket) and, if voice_enabled, spoken aloud - see alex/voice/pipeline.py.
    briefing_time: str = "07:30"
    briefing_news_rss_url: str = "https://feeds.bbci.co.uk/mundo/rss.xml"
    briefing_news_max_items: int = 5
    briefing_email_max_items: int = 5

    @field_validator("data_dir", "db_path", "log_dir", "tts_model_dir", mode="before")
    @classmethod
    def _expand(cls, v):
        return Path(v).expanduser() if v else v

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
