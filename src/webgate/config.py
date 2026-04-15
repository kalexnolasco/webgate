from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "WEBGATE_"}

    host: str = "0.0.0.0"
    port: int = 8443
    secret_key: str = "change-me-in-production"
    db_url: str = "sqlite+aiosqlite:///./webgate.db"
    allowed_origins: str = "*"
    root_path: str = ""  # URL prefix when served behind a reverse proxy (e.g. "/webgate")
    demo_mode: bool = False  # Read-only public demo: blocks writes, hides admin UI
    record_sessions: bool = False  # Capture SSH sessions to asciinema cast files
    recordings_dir: str = "./recordings"  # Where to store .cast files

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
