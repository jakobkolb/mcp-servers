from __future__ import annotations

from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field


class ICloudConfig(BaseModel):
    type: Literal["icloud"] = "icloud"
    name: str
    username: str
    password: str


class GoogleConfig(BaseModel):
    type: Literal["google"] = "google"
    name: str
    username: str
    password: str


class NextcloudConfig(BaseModel):
    type: Literal["nextcloud"] = "nextcloud"
    name: str
    url: str
    username: str
    password: str
    calendar_name: str | None = None
    verify_ssl: bool = True


CalendarConfig = Annotated[
    ICloudConfig | GoogleConfig | NextcloudConfig,
    Field(discriminator="type"),
]


class Config(BaseModel):
    calendars: list[CalendarConfig]


def load_config(path: str) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config.model_validate(data)


def build_backends(config: Config) -> list[object]:
    # Import here to avoid circular imports; return type is list[CalendarBackend]
    # but typed as list[object] to keep this module free of the backends dependency.
    from .backends import GoogleBackend, ICloudBackend, NextcloudBackend

    backends: list[object] = []
    for cfg in config.calendars:
        if isinstance(cfg, ICloudConfig):
            backends.append(ICloudBackend(cfg))
        elif isinstance(cfg, GoogleConfig):
            backends.append(GoogleBackend(cfg))
        elif isinstance(cfg, NextcloudConfig):
            backends.append(NextcloudBackend(cfg))
    return backends
