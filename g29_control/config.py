import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "network": {
        "pi_host": "192.168.0.102",
        "pi_port": 5005,
        "listen_host": "0.0.0.0",
        "listen_port": 5005,
        "hz": 80,
    },
    "input": {
        "steer_axis": 0,
        "throttle_axis": 2,
        "brake_axis": 3,
        "require_deadman": True,
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
        "forward_steer_boost": 0.7,
        "max_steer_gain": 1.2,
        "min_effective_pwm": 700,
        "in_place_speed_threshold": 0.08,
        "in_place_steer_threshold": 0.08,
        "in_place_turn_pwm": 1400,
    },
    "safety": {
        "timeout_ms": 350,
    },
    "logging": {
        "print_every_n": 20,
    },
    "camera_stream": {
        "host": "0.0.0.0",
        "host_client": "192.168.4.1",
        "port": 8001,
        "width": 1280,
        "height": 960,
        "hflip": False,
        "vflip": False,
        "client_hflip": False,
        "client_vflip": False,
        "client_display_width": 1280,
        "client_display_height": 960,
    },
    "servo_control": {
        "pi_host": "192.168.4.1",
        "pi_port": 5006,
        "listen_host": "0.0.0.0",
        "listen_port": 5006,
        "pan_channel": "0",
        "tilt_channel": "1",
        "step": 5,
        "invert_tilt": False,
        "min_angle": 0,
        "max_angle": 180,
        "home_pan": 90,
        "home_tilt": 90,
    },
    "quest_fpv": {
        "host": "0.0.0.0",
        "port": 8080,
        "https_enabled": False,
        "https_port": 8443,
        "tls_cert_path": "certs/quest_fpv.crt",
        "tls_key_path": "certs/quest_fpv.key",
        "http_redirect_to_https": True,
        "pan_channel": "0",
        "tilt_channel": "1",
        "min_angle": 0,
        "max_angle": 180,
        "home_pan": 90,
        "home_tilt": 90,
        "yaw_to_deg": 0.5,
        "pitch_to_deg": 0.5,
        "invert_tilt": False,
        "video_rotate_180": False,
        "xr_prefer_immersive": False,
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
