"""Flask app factory and routes for the AWS cost dashboard."""
from __future__ import annotations

from flask import Flask, jsonify, redirect, render_template, request, url_for

from aws_client import AwsAuthError
from config import Config, ConfigError, load_config
from providers import DashboardProvider, LiveProvider


def _parse_balance(raw: str | None) -> float | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def create_app(
    config: Config | None = None,
    provider: DashboardProvider | None = None,
) -> Flask:
    config = config or load_config()
    provider = provider or LiveProvider(config)
    app = Flask(__name__)

    @app.route("/")
    def index():
        error = None
        data = None
        try:
            data = provider.get(force=False)
        except (AwsAuthError, ConfigError, RuntimeError) as exc:
            error = str(exc)
        return render_template("dashboard.html", data=data, error=error)

    @app.route("/api/refresh", methods=["POST"])
    def refresh():
        try:
            data = provider.get(force=True)
        except (AwsAuthError, ConfigError, RuntimeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502
        return jsonify({"ok": True, "data": data.to_dict()})

    @app.route("/credits", methods=["POST"])
    def update_credits():
        account_id = request.form.get("account_id", "").strip()
        if account_id:
            provider.update_credit(
                account_id=account_id,
                balance=_parse_balance(request.form.get("balance")),
                expiry=(request.form.get("expiry") or "").strip() or None,
                note=(request.form.get("note") or "").strip() or None,
            )
        return redirect(url_for("index"))

    return app


def main() -> None:
    config = load_config()
    app = create_app(config)
    app.run(host=config.host, port=config.port, debug=False)


if __name__ == "__main__":
    main()
