import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "network": {
        "pi_host": "192.168.4.1",
        "pi_port": 5005,
        "listen_host": "0.0.0.0",
        "listen_port": 5005,
        "hz": 50,
    },
    "input": {
        "steer_axis": 0,
        "throttle_axis": 2,
        "brake_axis": 3,
        "deadman_button": 4,
        "estop_button": 1,
        "reset_estop_button": 2,
        "invert_steer": False,
        "invert_throttle": True,
        "invert_brake": True,
        "deadzone": 0.05,
        "axis_min": {"steer": -1.0, "throttle": -1.0, "brake": -1.0},
        "axis_max": {"steer": 1.0, "throttle": 1.0, "brake": 1.0},
    },
    "mapping": {
        "max_pwm": 2800,
        "steer_gain": 0.7,
    },
    "safety": {
        "timeout_ms": 350,
    },
    "logging": {
        "print_every_n": 20,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    with path.open("r", encoding="utf-8") as f:
        user_cfg = json.load(f)
    return _deep_merge(DEFAULT_CONFIG, user_cfg)
