"""Tests for config loading and backend construction."""

import os
import tempfile
import textwrap

import pytest
from mcp_calendar.backends import GoogleBackend, ICloudBackend, NextcloudBackend
from mcp_calendar.config import (
    Config,
    GoogleConfig,
    ICloudConfig,
    NextcloudConfig,
    build_backends,
    load_config,
)
from pydantic import ValidationError


def _write_yaml(content: str) -> str:
    """Write YAML content to a temp file and return path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.write(fd, textwrap.dedent(content).encode())
    os.close(fd)
    return path


def test_load_all_three_backends() -> None:
    path = _write_yaml("""
        calendars:
          - type: icloud
            name: personal
            username: user@icloud.com
            password: secret1
          - type: google
            name: work
            username: user@gmail.com
            password: secret2
          - type: nextcloud
            name: shared
            url: https://cloud.example.com
            username: alice
            password: secret3
            calendar_name: Family
            verify_ssl: false
    """)
    try:
        config = load_config(path)
        assert len(config.calendars) == 3
        icloud_cfg, google_cfg, nc_cfg = config.calendars
        assert isinstance(icloud_cfg, ICloudConfig)
        assert isinstance(google_cfg, GoogleConfig)
        assert isinstance(nc_cfg, NextcloudConfig)
        assert icloud_cfg.name == "personal"
        assert google_cfg.name == "work"
        assert nc_cfg.calendar_name == "Family"
        assert nc_cfg.verify_ssl is False
    finally:
        os.unlink(path)


def test_load_nextcloud_defaults() -> None:
    path = _write_yaml("""
        calendars:
          - type: nextcloud
            name: mycloud
            url: https://cloud.example.com
            username: bob
            password: pass
    """)
    try:
        config = load_config(path)
        nc = config.calendars[0]
        assert isinstance(nc, NextcloudConfig)
        assert nc.calendar_name is None
        assert nc.verify_ssl is True
    finally:
        os.unlink(path)


def test_missing_required_field_raises_validation_error() -> None:
    path = _write_yaml("""
        calendars:
          - type: icloud
            name: personal
            username: user@icloud.com
            # password is missing
    """)
    try:
        with pytest.raises(ValidationError):
            load_config(path)
    finally:
        os.unlink(path)


def test_unknown_type_raises_validation_error() -> None:
    path = _write_yaml("""
        calendars:
          - type: caldav
            name: other
            url: https://example.com
            username: user
            password: pass
    """)
    try:
        with pytest.raises(ValidationError):
            load_config(path)
    finally:
        os.unlink(path)


def test_build_backends_returns_correct_classes() -> None:
    config = Config.model_validate(
        {
            "calendars": [
                {"type": "icloud", "name": "ic", "username": "u", "password": "p"},
                {"type": "google", "name": "goog", "username": "u", "password": "p"},
                {
                    "type": "nextcloud",
                    "name": "nc",
                    "url": "https://cloud.example.com",
                    "username": "u",
                    "password": "p",
                },
            ]
        }
    )
    backends = build_backends(config)
    assert len(backends) == 3
    assert isinstance(backends[0], ICloudBackend)
    assert isinstance(backends[1], GoogleBackend)
    assert isinstance(backends[2], NextcloudBackend)
