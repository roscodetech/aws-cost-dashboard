"""Unit tests for configuration loading and validation."""
from __future__ import annotations

import pytest

import config as config_mod
from config import (
    DEFAULT_CACHE_TTL,
    DEFAULT_PORT,
    Config,
    ConfigError,
    load_config,
)

_CRED_VARS = (
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "CACHE_TTL_SECONDS",
    "FLASK_HOST",
    "FLASK_PORT",
)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Clear all AWS/config env vars and point load_dotenv at a missing file.

    Patching ``load_dotenv`` to a no-op guarantees the developer's real ``.env``
    can never leak into the test, regardless of the env_path passed.
    """
    for var in _CRED_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config_mod, "load_dotenv", lambda *a, **k: False)
    return tmp_path / "does-not-exist.env"


def test_raises_when_no_profile_and_no_keys(clean_env):
    with pytest.raises(ConfigError, match="No AWS credentials"):
        load_config(env_path=clean_env)


def test_returns_config_when_profile_set(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    cfg = load_config(env_path=clean_env)
    assert isinstance(cfg, Config)
    assert cfg.profile == "billing"
    assert cfg.uses_profile is True
    assert cfg.access_key_id is None
    # Defaults applied.
    assert cfg.cache_ttl_seconds == DEFAULT_CACHE_TTL
    assert cfg.port == DEFAULT_PORT
    assert cfg.region == config_mod.DEFAULT_REGION


def test_returns_config_when_both_keys_set(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    cfg = load_config(env_path=clean_env)
    assert cfg.uses_profile is False
    assert cfg.access_key_id == "AKIA"
    assert cfg.secret_access_key == "secret"


def test_raises_when_only_access_key_present(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    with pytest.raises(ConfigError, match="No AWS credentials"):
        load_config(env_path=clean_env)


def test_cache_ttl_parsed_as_int(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "120")
    cfg = load_config(env_path=clean_env)
    assert cfg.cache_ttl_seconds == 120
    assert isinstance(cfg.cache_ttl_seconds, int)


def test_bad_cache_ttl_raises_config_error(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "not-a-number")
    with pytest.raises(ConfigError, match="CACHE_TTL_SECONDS must be an integer"):
        load_config(env_path=clean_env)


def test_bad_port_raises_config_error(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("FLASK_PORT", "abc")
    with pytest.raises(ConfigError, match="FLASK_PORT must be an integer"):
        load_config(env_path=clean_env)


def test_empty_ttl_falls_back_to_default(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "   ")
    cfg = load_config(env_path=clean_env)
    assert cfg.cache_ttl_seconds == DEFAULT_CACHE_TTL


def test_custom_region_and_host(clean_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("FLASK_HOST", "0.0.0.0")
    cfg = load_config(env_path=clean_env)
    assert cfg.region == "eu-west-1"
    assert cfg.host == "0.0.0.0"
