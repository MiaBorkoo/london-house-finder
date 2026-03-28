"""Flask web server for health checks, stats, and listing views."""

import logging

from flask import Flask, jsonify, request

from core.database import Database
from notifications.ntfy_sender import NtfySender

logger = logging.getLogger(__name__)


def create_app(database: Database, ntfy_sender: NtfySender, config: dict) -> Flask:
    """Create and configure the Flask app."""
    app = Flask(__name__)

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/stats")
    def stats():
        try:
            return jsonify(database.get_stats())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/listings/recent")
    def recent_listings():
        hours = request.args.get("hours", 24, type=int)
        try:
            listings = database.get_recent_properties(hours)
            return jsonify({"count": len(listings), "listings": listings})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/listings/hot")
    def hot_listings():
        try:
            listings = database.get_hot_unnotified()
            return jsonify({"count": len(listings), "listings": listings})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app


def run_server(database: Database, ntfy_sender: NtfySender, config: dict):
    """Run the Flask server (intended for background thread)."""
    server_config = config.get("server", {})
    host = server_config.get("host", "0.0.0.0")
    port = server_config.get("port", 5151)
    debug = server_config.get("debug", False)

    app = create_app(database, ntfy_sender, config)
    app.run(host=host, port=port, debug=debug, threaded=True)
