from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "WEBGATE_"}

    host: str = "0.0.0.0"
    port: int = 8443
    secret_key: str = "change-me-in-production"
    # Trust-on-first-use host key pinning. Off only makes sense in a throwaway lab:
    # without it the gateway hands stored credentials to whatever answers.
    verify_host_keys: bool = True
    db_url: str = "sqlite+aiosqlite:///./webgate.db"
    allowed_origins: str = "*"
    root_path: str = ""  # URL prefix when served behind a reverse proxy (e.g. "/webgate")
    # Makes the admin settings panel read-only, for deployments whose configuration
    # is managed as code and should not drift from what the manifest says.
    config_locked: bool = False
    # Start even with the shipped default secret_key on a non-loopback bind.
    allow_insecure_secret: bool = False
    demo_mode: bool = False  # Read-only public demo: blocks writes, hides admin UI

    # --- Diagnostic agent (opt-in, off by default) ---
    # The agent reads command output from the inspected host and sends it to a model,
    # so it stays off unless an operator turns it on, and each server opts in too.
    agent_enabled: bool = False
    # "ollama" keeps everything on your own network; "openrouter" is managed and needs a key.
    agent_provider: str = "ollama"
    agent_base_url: str = ""  # blank -> http://localhost:11434 or https://openrouter.ai/api
    agent_api_key: str = ""  # required for openrouter
    agent_model: str = ""  # blank -> operator picks one in the UI
    agent_max_steps: int = 12  # model rounds per question; a round may call several tools
    agent_command_timeout: int = 20  # seconds per remote command
    agent_context_budget: int = 24000  # approx tokens of transcript kept per conversation
    agent_cache_ttl: int = 60  # seconds a tool result may be reused; 0 disables
    agent_findings_retention_days: int = 90  # 0 keeps findings forever
    # Only the GATEWAY needs a route to the model — the inspected hosts never do, they
    # are reached over SSH from here. Behind a corporate proxy, set agent_proxy_url.
    agent_proxy_url: str = ""
    agent_request_timeout: int = 120  # fail fast instead of hanging on a blackholed route
    record_sessions: bool = False  # Capture SSH sessions to asciinema cast files
    recordings_dir: str = "./recordings"  # Scratch space while a session is live
    recording_max_bytes: int = 25 * 1024 * 1024  # per session; 0 removes the cap

    # LDAP / Active Directory
    ldap_enabled: bool = False
    ldap_url: str = ""  # e.g. ldap://ldap.example.com:389 or ldaps://...
    ldap_bind_dn: str = ""  # service account DN, e.g. cn=admin,dc=example,dc=com
    ldap_bind_password: str = ""
    ldap_user_base: str = ""  # e.g. ou=people,dc=example,dc=com
    ldap_user_filter: str = "(uid={username})"  # AD: (sAMAccountName={username})
    ldap_group_base: str = ""  # e.g. ou=groups,dc=example,dc=com (empty = no group lookup)
    ldap_group_filter: str = "(member={dn})"  # AD: (member:1.2.840.113556.1.4.1941:={dn})
    ldap_group_map: str = "{}"  # JSON: {"ldap-group-cn": "webgate-group-name"}
    ldap_admin_groups: str = "[]"  # JSON list of LDAP group CNs that grant admin

    # Multi-instance HA
    instance_id: str = ""  # Unique per worker; auto-generated UUID if empty
    disable_monitor: bool = False  # Skip leader election; never run server monitor
    log_level: str = "info"
    session_timeout: int = 3600
    max_upload_size: int = 104857600  # 100MB
    first_run: bool = True

    # JWT settings
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # Server monitoring
    monitor_interval: int = 60  # seconds between connectivity checks
    monitor_timeout: int = 5  # SSH connect timeout for checks
    monitor_concurrency: int = 10  # max parallel checks

    @property
    def static_dir(self) -> Path:
        return Path(__file__).parent / "static"


settings = Settings()
