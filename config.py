"""Configuration loading and validation (system boundary).

Resolves credentials and runtime settings from environment / .env. Fails fast with
a clear message when neither a profile nor explicit keys are available.
"""
from __future__ import annotations

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
class Config:
    profile: str | None
    access_key_id: str | None
    secret_access_key: str | None
    region: str
    cache_ttl_seconds: int
    cache_path: Path
    credits_path: Path
    host: str
    port: int

    @property
    def uses_profile(self) -> bool:
        return bool(self.profile)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def load_config(env_path: Path | None = None) -> Config:
    """Load and validate configuration. Call once at startup."""
    load_dotenv(env_path or PROJECT_ROOT / ".env")

    profile = os.getenv("AWS_PROFILE") or None
    access_key = os.getenv("AWS_ACCESS_KEY_ID") or None
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY") or None

    if not profile and not (access_key and secret_key):
        raise ConfigError(
            "No AWS credentials found. Set AWS_PROFILE, or both "
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, in your .env "
            "(copy .env.example). Use the read-only IAM user, never root."
        )

    return Config(
        profile=profile,
        access_key_id=access_key,
        secret_access_key=secret_key,
        region=os.getenv("AWS_REGION") or DEFAULT_REGION,
        cache_ttl_seconds=_int_env("CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL),
        cache_path=PROJECT_ROOT / "cache.json",
        credits_path=PROJECT_ROOT / "credits.json",
        host=os.getenv("FLASK_HOST") or DEFAULT_HOST,
        port=_int_env("FLASK_PORT", DEFAULT_PORT),
    )
