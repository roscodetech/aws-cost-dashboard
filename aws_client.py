"""boto3 session and client construction (system boundary).

Builds a single session from the resolved Config and hands out the three clients
the services need. Validates credentials with one cheap call so the app fails fast.
"""
from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import Config


class AwsAuthError(RuntimeError):
    """Raised when credentials are missing, invalid, or lack billing access."""


class AwsClients:
    """Lazily-built, cached boto3 clients sharing one session."""

    def __init__(self, config: Config) -> None:
        self._config = config
        if config.uses_profile:
            self._session = boto3.Session(
                profile_name=config.profile, region_name=config.region
            )
        else:
            self._session = boto3.Session(
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
                region_name=config.region,
            )
        self._cache: dict[str, object] = {}

    def _client(self, name: str):
        if name not in self._cache:
            self._cache[name] = self._session.client(name)
        return self._cache[name]

    @property
    def cost_explorer(self):
        return self._client("ce")

    @property
    def budgets(self):
        return self._client("budgets")

    @property
    def organizations(self):
        return self._client("organizations")

    @property
    def sts(self):
        return self._client("sts")

    def validate(self) -> str:
        """Cheap read to confirm creds work. Returns the caller's account id.

        Uses STS GetCallerIdentity (always allowed for any valid principal and
        works whether or not the account belongs to an Organization).
        """
        try:
            return self.sts.get_caller_identity()["Account"]
        except (ClientError, BotoCoreError) as exc:
            raise AwsAuthError(
                "AWS credentials are missing or invalid. Check the access key "
                f"and secret in your .env. ({exc})"
            ) from exc
