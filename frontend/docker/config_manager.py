import json
import os
import structlog
from typing import Dict, Any
from constants import DEFAULTS

logger = structlog.get_logger(__name__)

CONFIG_FILE = os.path.join('/app/data', 'api_config.json')

def save_config(config: Dict[str, Any]) -> str:
    """Save configuration to file."""
    try:
        # Ensure directory exists in case of local testing
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
        return "Configuration saved successfully"
    except Exception as e:
        logger.error("config_save_failed", error=str(e))
        return f"Failed to save configuration: {str(e)}"

def load_config() -> Dict[str, Any]:
    """Load configuration from file or use defaults."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                for service in DEFAULTS:
                    if service not in loaded_config:
                        loaded_config[service] = DEFAULTS[service]
                return loaded_config
        return DEFAULTS
    except Exception as e:
        logger.error("config_load_failed", error=str(e))
        return DEFAULTS
