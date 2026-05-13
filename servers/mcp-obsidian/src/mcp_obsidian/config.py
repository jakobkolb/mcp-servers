from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    vault_path: str
    mcp_transport: str = "streamable-http"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
