"""Unit tests for multi-account configuration loading and validation.

``load_config`` reads ``accounts.json`` from ``config.PROJECT_ROOT`` (the real
project dir). A real ``accounts.json`` may exist there, so every test monkeypatches
``config.PROJECT_ROOT`` to an isolated ``tmp_path`` so the developer's real config
can never leak in. The ``.env`` fallback tests additionally stub ``load_dotenv`` to a
no-op so the real ``.env`` can't leak either.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import config as config_mod
from config import (
    DEFAULT_CACHE_TTL,
    DEFAULT_PORT,
    DEFAULT_REGION,
    AccountConfig,
    Config,
    ConfigError,
    load_config,
)

_CRED_VARS = (
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "AWS_ACCOUNT_LABEL",
    "CACHE_TTL_SECONDS",
    "FLASK_HOST",
    "FLASK_PORT",
)


@pytest.fixture
def isolated_root(monkeypatch, tmp_path):
    """Point ``config.PROJECT_ROOT`` at an empty tmp dir and clear all config env.

    No ``accounts.json`` exists in the tmp dir, so by default this drives the
    .env fallback path. ``load_dotenv`` is stubbed to a no-op so the real ``.env``
    can never leak in.
    """
    for var in _CRED_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "load_dotenv", lambda *a, **k: False)
    return tmp_path


def _write_accounts(root: Path, payload) -> None:
    (root / "accounts.json").write_text(
        json.dumps(payload) if not isinstance(payload, str) else payload,
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# accounts.json path
# --------------------------------------------------------------------------- #
def test_loads_two_accounts_from_accounts_json(isolated_root):
    _write_accounts(
        isolated_root,
        [
            {"label": "prod", "profile": "billing", "region": "eu-west-1"},
            {
                "label": "dev",
                "access_key_id": "AKIA",
                "secret_access_key": "secret",
            },
        ],
    )
    cfg = load_config()

    assert isinstance(cfg, Config)
    assert len(cfg.accounts) == 2

    prod, dev = cfg.accounts
    assert prod == AccountConfig(
        label="prod", profile="billing", region="eu-west-1"
    )
    assert prod.uses_profile is True

    assert dev.label == "dev"
    assert dev.profile is None
    assert dev.access_key_id == "AKIA"
    assert dev.secret_access_key == "secret"
    assert dev.region == DEFAULT_REGION  # default applied
    assert dev.uses_profile is False


def test_accounts_json_path_is_project_root_join(isolated_root, monkeypatch):
    """load_config builds the path as PROJECT_ROOT / 'accounts.json'."""
    seen: list[Path] = []
    real_loader = config_mod._load_accounts

    def spy(path: Path):
        seen.append(path)
        return real_loader(path)

    monkeypatch.setattr(config_mod, "_load_accounts", spy)
    _write_accounts(isolated_root, [{"label": "prod", "profile": "billing"}])

    load_config()

    assert seen == [isolated_root / "accounts.json"]


def test_entry_missing_label_raises(isolated_root):
    _write_accounts(isolated_root, [{"profile": "billing"}])
    with pytest.raises(ConfigError, match="missing a 'label'"):
        load_config()


def test_entry_without_profile_or_keys_raises(isolated_root):
    _write_accounts(isolated_root, [{"label": "prod"}])
    with pytest.raises(ConfigError, match="needs either 'profile'"):
        load_config()


def test_entry_with_only_access_key_raises(isolated_root):
    _write_accounts(isolated_root, [{"label": "prod", "access_key_id": "AKIA"}])
    with pytest.raises(ConfigError, match="needs either 'profile'"):
        load_config()


def test_accounts_json_not_an_array_raises(isolated_root):
    _write_accounts(isolated_root, {"label": "prod", "profile": "billing"})
    with pytest.raises(ConfigError, match="non-empty JSON array"):
        load_config()


def test_accounts_json_empty_array_raises(isolated_root):
    _write_accounts(isolated_root, [])
    with pytest.raises(ConfigError, match="non-empty JSON array"):
        load_config()


def test_accounts_json_invalid_json_raises(isolated_root):
    _write_accounts(isolated_root, "{not valid json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config()


# --------------------------------------------------------------------------- #
# .env fallback path (no accounts.json present)
# --------------------------------------------------------------------------- #
def test_fallback_profile_default_label(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    cfg = load_config()

    assert len(cfg.accounts) == 1
    acct = cfg.accounts[0]
    assert acct.label == "default"
    assert acct.profile == "billing"
    assert acct.uses_profile is True
    assert acct.access_key_id is None
    assert acct.region == DEFAULT_REGION
    # Config-level defaults applied.
    assert cfg.cache_ttl_seconds == DEFAULT_CACHE_TTL
    assert cfg.port == DEFAULT_PORT


def test_fallback_custom_account_label(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("AWS_ACCOUNT_LABEL", "personal")
    cfg = load_config()
    assert cfg.accounts[0].label == "personal"


def test_fallback_from_access_keys(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    cfg = load_config()
    acct = cfg.accounts[0]
    assert acct.uses_profile is False
    assert acct.access_key_id == "AKIA"
    assert acct.secret_access_key == "secret"


def test_fallback_raises_when_no_creds(isolated_root):
    with pytest.raises(ConfigError, match="No accounts configured"):
        load_config()


def test_fallback_raises_when_only_access_key(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA")
    with pytest.raises(ConfigError, match="No accounts configured"):
        load_config()


# --------------------------------------------------------------------------- #
# Config-level parsing (exercised via the fallback account)
# --------------------------------------------------------------------------- #
def test_cache_ttl_parsed_as_int(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "120")
    cfg = load_config()
    assert cfg.cache_ttl_seconds == 120
    assert isinstance(cfg.cache_ttl_seconds, int)


def test_bad_cache_ttl_raises_config_error(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "not-a-number")
    with pytest.raises(ConfigError, match="CACHE_TTL_SECONDS must be an integer"):
        load_config()


def test_empty_ttl_falls_back_to_default(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "   ")
    cfg = load_config()
    assert cfg.cache_ttl_seconds == DEFAULT_CACHE_TTL


def test_bad_port_raises_config_error(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("FLASK_PORT", "abc")
    with pytest.raises(ConfigError, match="FLASK_PORT must be an integer"):
        load_config()


def test_custom_region_and_host_on_fallback(isolated_root, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "billing")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("FLASK_HOST", "0.0.0.0")
    cfg = load_config()
    assert cfg.accounts[0].region == "eu-west-1"
    assert cfg.host == "0.0.0.0"
