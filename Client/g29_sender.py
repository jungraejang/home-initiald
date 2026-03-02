import argparse
import os
import socket
import sys
import time
from pathlib import Path
from typing import Tuple

import pygame

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from g29_control.config import load_config
from g29_control.protocol import ControlPacket


if sys.platform.startswith("win"):
    # Improve wheel detection reliability on Windows SDL backend.
    os.environ.setdefault("SDL_JOYSTICK_RAWINPUT", "1")


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def map_axis_signed(raw: float, axis_min: float, axis_max: float, invert: bool, deadzone: float) -> float:
    if axis_max == axis_min:
        return 0.0
    scaled = ((raw - axis_min) / (axis_max - axis_min)) * 2.0 - 1.0
    scaled = clamp(scaled, -1.0, 1.0)
    if invert:
        scaled = -scaled
    if abs(scaled) < deadzone:
        return 0.0
    return scaled


def map_axis_01(raw: float, axis_min: float, axis_max: float, invert: bool) -> float:
    if axis_max == axis_min:
        return 0.0
    scaled = (raw - axis_min) / (axis_max - axis_min)
    scaled = clamp(scaled, 0.0, 1.0)
    if invert:
        scaled = 1.0 - scaled
    return scaled


def get_button_safe(joystick: pygame.joystick.Joystick, button_index: int, default: bool = False) -> bool:
    if button_index < 0 or button_index >= joystick.get_numbuttons():
        return default
    return bool(joystick.get_button(button_index))


def list_joysticks() -> list[tuple[int, str]]:
    pygame.joystick.quit()
    pygame.joystick.init()
    pygame.event.pump()
    devices = []
    for idx in range(pygame.joystick.get_count()):
        js = pygame.joystick.Joystick(idx)
        js.init()
        devices.append((idx, js.get_name()))
    return devices


def find_g29_joystick(wait_seconds: float = 8.0, device_index: int | None = None) -> pygame.joystick.Joystick:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    warned_waiting = False
    while True:
        devices = list_joysticks()
        if devices:
            if device_index is not None:
                if 0 <= device_index < len(devices):
                    js = pygame.joystick.Joystick(device_index)
                    js.init()
                    return js
                raise RuntimeError(
                    f"--device-index {device_index} is invalid. Found {len(devices)} device(s): {devices}"
                )

            preferred_index = None
            for idx, name in devices:
                lname = name.lower()
                if "g29" in lname or "driving force" in lname or ("logitech" in lname and "wheel" in lname):
                    preferred_index = idx
                    break
            if preferred_index is None:
                preferred_index = devices[0][0]
            js = pygame.joystick.Joystick(preferred_index)
            js.init()
            return js

        if time.monotonic() >= deadline:
            raise RuntimeError(
                "No joystick/game controller detected by SDL/pygame.\n"
                "Checks:\n"
                "1) Connect wheel USB directly (avoid hub), power on wheel.\n"
                "2) Set G29 mode switch to PS4 (or test PS3 if needed).\n"
                "3) Confirm in Windows 'Set up USB game controllers' that the wheel appears.\n"
                "4) Close apps that may lock the device and rerun with --wait-seconds 15.\n"
                "5) Run with --list-devices to inspect what pygame sees."
            )
        if not warned_waiting:
            print("Waiting for joystick detection...")
            warned_waiting = True
        time.sleep(0.5)


def calibrate(joystick: pygame.joystick.Joystick, seconds: float) -> Tuple[dict, dict]:
    print(f"Calibrating for {seconds:.1f}s. Move wheel full left/right and press/release pedals.")
    axis_min = {}
    axis_max = {}
    axis_count = joystick.get_numaxes()
    for i in range(axis_count):
        raw = joystick.get_axis(i)
        axis_min[i] = raw
        axis_max[i] = raw

    start = time.monotonic()
    while time.monotonic() - start < seconds:
        pygame.event.pump()
        for i in range(axis_count):
            raw = joystick.get_axis(i)
            axis_min[i] = min(axis_min[i], raw)
            axis_max[i] = max(axis_max[i], raw)
        time.sleep(0.01)
    return axis_min, axis_max


def main() -> None:
    parser = argparse.ArgumentParser(description="G29 UDP sender for Raspberry Pi RC car")
    parser.add_argument("--config", default=str(ROOT / "g29_control" / "config.json"))
    parser.add_argument("--calibrate-seconds", type=float, default=0.0)
    parser.add_argument("--wait-seconds", type=float, default=8.0)
    parser.add_argument("--device-index", type=int, default=None)
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    net = cfg["network"]
    inp = cfg["input"]
    log_cfg = cfg["logging"]

    pygame.init()
    if args.list_devices:
        devices = list_joysticks()
        if not devices:
            print("No joystick devices detected by pygame.")
        else:
            print("Detected joystick devices:")
            for idx, name in devices:
                print(f"  [{idx}] {name}")
        pygame.quit()
        return

    joystick = find_g29_joystick(wait_seconds=args.wait_seconds, device_index=args.device_index)
    print(f"Using controller: {joystick.get_name()}")
    print(f"Axes={joystick.get_numaxes()} Buttons={joystick.get_numbuttons()}")

    if args.calibrate_seconds > 0:
        mins, maxs = calibrate(joystick, args.calibrate_seconds)
        print("Calibration results:")
        for k in sorted(mins.keys()):
            print(f"  axis {k}: min={mins[k]:.4f} max={maxs[k]:.4f}")

    target = (net["pi_host"], int(net["pi_port"]))
    hz = max(1, int(net["hz"]))
    period = 1.0 / hz
    print_every_n = max(1, int(log_cfg["print_every_n"]))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Sending to {target[0]}:{target[1]} at {hz} Hz")

    seq = 0
    send_count = 0
    log_window_start = time.monotonic()
    try:
        while True:
            loop_start = time.monotonic()
            pygame.event.pump()
            steer_raw = joystick.get_axis(int(inp["steer_axis"]))
            throttle_raw = joystick.get_axis(int(inp["throttle_axis"]))
            brake_raw = joystick.get_axis(int(inp["brake_axis"]))

            steer = map_axis_signed(
                steer_raw,
                float(inp["axis_min"]["steer"]),
                float(inp["axis_max"]["steer"]),
                bool(inp["invert_steer"]),
                float(inp["deadzone"]),
            )
            throttle = map_axis_01(
                throttle_raw,
                float(inp["axis_min"]["throttle"]),
                float(inp["axis_max"]["throttle"]),
                bool(inp["invert_throttle"]),
            )
            brake = map_axis_01(
                brake_raw,
                float(inp["axis_min"]["brake"]),
                float(inp["axis_max"]["brake"]),
                bool(inp["invert_brake"]),
            )

            require_deadman = bool(inp.get("require_deadman", True))
            deadman_button = int(inp.get("deadman_button", 4))
            estop_button = int(inp.get("estop_button", 1))
            reset_estop_button = int(inp.get("reset_estop_button", 2))

            deadman = (
                get_button_safe(joystick, deadman_button, default=False)
                if require_deadman
                else True
            )
            estop = get_button_safe(joystick, estop_button, default=False)
            reset_estop = get_button_safe(joystick, reset_estop_button, default=False)

            packet = ControlPacket.create(
                seq=seq,
                steer=steer,
                throttle=throttle,
                brake=brake,
                deadman=deadman,
                estop=estop,
                reset_estop=reset_estop,
            )
            sock.sendto(packet.to_bytes(), target)
            seq += 1
            send_count += 1

            if send_count % print_every_n == 0:
                elapsed = max(1e-6, time.monotonic() - log_window_start)
                rate = print_every_n / elapsed
                log_window_start = time.monotonic()
                print(
                    f"seq={packet.seq} steer={packet.steer:+.2f} "
                    f"throttle={packet.throttle:.2f} brake={packet.brake:.2f} "
                    f"deadman={int(packet.deadman)} estop={int(packet.estop)} tx={rate:.1f}Hz"
                )

            loop_elapsed = time.monotonic() - loop_start
            sleep_time = period - loop_elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        print("\nStopping G29 sender.")
    finally:
        sock.close()
        pygame.quit()


if __name__ == "__main__":
    main()
