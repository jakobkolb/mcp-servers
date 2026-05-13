from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    vault_path: str
    mcp_transport: str = "streamable-http"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    qmd_url: str | None = None
    log_level: str = "INFO"
    search_limit_max: int = 20
    max_batch_read: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
