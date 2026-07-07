"""Configuration for CricFloat. Env-overridable."""

from __future__ import annotations

import os

# CricAPI free key (fallback provider only). Get one at https://cricapi.com.
# Leave empty to disable the fallback.
CRICAPI_KEY: str = os.environ.get("CRICAPI_KEY", "")

# Poll cadence (seconds). Live is short so batsman/bowler stay fresh — ESPN's
# summary endpoint updates within ~10-30s, so a 10s poll surfaces changes soon
# after the source does. (The remaining lag is ESPN's own; its real-time
# hs-consumer-api that the website uses is Cloudflare-blocked for us.)
POLL_INTERVAL_LIVE: float = float(os.environ.get("CRICFLOAT_POLL_LIVE", "10"))
POLL_INTERVAL_IDLE: float = float(os.environ.get("CRICFLOAT_POLL_IDLE", "300"))

HTTP_TIMEOUT: float = float(os.environ.get("CRICFLOAT_HTTP_TIMEOUT", "12"))
