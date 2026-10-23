import os
import requests
import logging

logger = logging.getLogger("pipeline.orchestration.alerts")


def send_discord_alert(message: str):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return

    try:
        requests.post(webhook_url, json={"content": f"🚨 **Globe News Atlas Pipeline Alert**: {message}"}, timeout=5)
    except Exception as e:
        logger.warning(f"Could not send Discord alert: {e}")
