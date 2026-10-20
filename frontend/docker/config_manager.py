import json
import os
from typing import Any

import structlog

from constants import DEFAULTS

logger = structlog.get_logger(__name__)

CONFIG_FILE = os.path.join("/app/data", "api_config.json")


def save_config(config: dict[str, Any]) -> str:
    """Save configuration to file."""
    try:
        # Ensure directory exists in case of local testing
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f)
        return "Configuration saved successfully"
    except Exception as e:
        logger.error("config_save_failed", error=str(e))
        return f"Failed to save configuration: {e!s}"


def load_config() -> dict[str, Any]:
    """Load configuration from file or use defaults."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                loaded_config: dict[str, Any] = json.load(f)
                # Fill services and fields added since the file was saved.
                for service, defaults in DEFAULTS.items():
                    loaded_config[service] = {**defaults, **loaded_config.get(service, {})}
                return loaded_config
        return DEFAULTS
    except Exception as e:
        logger.error("config_load_failed", error=str(e))
        return DEFAULTS
