"""Configuration loading and validation (system boundary).

Supports multiple AWS accounts. Accounts come from a gitignored ``accounts.json``
in the project root; if that file is absent, a single account is read from ``.env``
(backward compatible). Fails fast with a clear message when nothing is configured.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_REGION = "us-east-1"
DEFAULT_CACHE_TTL = 3600
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5057


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class AccountConfig:
    """Credentials + label for one AWS account."""

    label: str
    profile: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    region: str = DEFAULT_REGION

    @property
    def uses_profile(self) -> bool:
        return bool(self.profile)


@dataclass(frozen=True)
class Config:
    accounts: tuple[AccountConfig, ...]
    cache_ttl_seconds: int
    cache_path: Path
    credits_path: Path
    host: str
    port: int


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _account_from_entry(entry: dict, index: int) -> AccountConfig:
    label = str(entry.get("label") or "").strip()
    if not label:
        raise ConfigError(f"accounts.json[{index}] is missing a 'label'.")
    profile = entry.get("profile") or None
    access_key = entry.get("access_key_id") or None
    secret_key = entry.get("secret_access_key") or None
    if not profile and not (access_key and secret_key):
        raise ConfigError(
            f"accounts.json entry '{label}' needs either 'profile' or both "
            "'access_key_id' and 'secret_access_key'."
        )
    return AccountConfig(
        label=label,
        profile=profile,
        access_key_id=access_key,
        secret_access_key=secret_key,
        region=entry.get("region") or DEFAULT_REGION,
    )


def _load_accounts(accounts_path: Path) -> tuple[AccountConfig, ...]:
    """accounts.json if present, else a single account from .env."""
    if accounts_path.exists():
        try:
            raw = json.loads(accounts_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigError(f"accounts.json is not valid JSON: {exc}") from exc
        if not isinstance(raw, list) or not raw:
            raise ConfigError("accounts.json must be a non-empty JSON array.")
        return tuple(_account_from_entry(e, i) for i, e in enumerate(raw))

    # Fallback: single account from environment / .env
    profile = os.getenv("AWS_PROFILE") or None
    access_key = os.getenv("AWS_ACCESS_KEY_ID") or None
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY") or None
    if not profile and not (access_key and secret_key):
        raise ConfigError(
            "No accounts configured. Create accounts.json (see "
            "accounts.example.json), or set AWS_PROFILE / "
            "AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY in .env. Never use root."
        )
    return (
        AccountConfig(
            label=os.getenv("AWS_ACCOUNT_LABEL") or "default",
            profile=profile,
            access_key_id=access_key,
            secret_access_key=secret_key,
            region=os.getenv("AWS_REGION") or DEFAULT_REGION,
        ),
    )


def load_config(env_path: Path | None = None) -> Config:
    """Load and validate configuration. Call once at startup."""
    load_dotenv(env_path or PROJECT_ROOT / ".env")
    return Config(
        accounts=_load_accounts(PROJECT_ROOT / "accounts.json"),
        cache_ttl_seconds=_int_env("CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL),
        cache_path=PROJECT_ROOT / "cache.json",
        credits_path=PROJECT_ROOT / "credits.json",
        host=os.getenv("FLASK_HOST") or DEFAULT_HOST,
        port=_int_env("FLASK_PORT", DEFAULT_PORT),
    )
