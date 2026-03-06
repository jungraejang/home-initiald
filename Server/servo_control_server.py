import argparse
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from g29_control.config import load_config
from servo import Servo


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pi UDP server for camera pan/tilt servos")
    parser.add_argument("--config", default=str(ROOT / "g29_control" / "config.json"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    scfg = cfg.get("servo_control", {})
    host = scfg.get("listen_host", "0.0.0.0")
    port = int(scfg.get("listen_port", 5006))
    pan_channel = str(scfg.get("pan_channel", "0"))
    tilt_channel = str(scfg.get("tilt_channel", "1"))
    min_angle = int(scfg.get("min_angle", 0))
    max_angle = int(scfg.get("max_angle", 180))
    home_pan = int(scfg.get("home_pan", 90))
    home_tilt = int(scfg.get("home_tilt", 90))
    print_every_n = int(cfg.get("logging", {}).get("print_every_n", 20))

    servo = Servo()
    pan = clamp(home_pan, min_angle, max_angle)
    tilt = clamp(home_tilt, min_angle, max_angle)
    servo.set_servo_pwm(pan_channel, pan)
    servo.set_servo_pwm(tilt_channel, tilt)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"Servo control listening on {host}:{port} (pan_ch={pan_channel}, tilt_ch={tilt_channel})")

    count = 0
    try:
        while True:
            raw, src = sock.recvfrom(1024)
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception:
                continue

            if msg.get("type") != "servo_cmd":
                continue

            # Absolute angle command, clamped to safe range.
            pan = clamp(int(msg.get("pan", pan)), min_angle, max_angle)
            tilt = clamp(int(msg.get("tilt", tilt)), min_angle, max_angle)
            try:
                servo.set_servo_pwm(pan_channel, pan)
                servo.set_servo_pwm(tilt_channel, tilt)
            except Exception as exc:
                print(f"Servo update failed from {src}: {exc}")
                continue

            count += 1
            if count % max(1, print_every_n) == 0:
                print(f"servo pan={pan} tilt={tilt}")
    except KeyboardInterrupt:
        print("\nStopping servo control server.")
    finally:
        try:
            servo.pwm_servo.close()
        except Exception:
            pass
        sock.close()


if __name__ == "__main__":
    main()
