import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = str(ROOT / "g29_control" / "config.json")


class ProcessSpec(NamedTuple):
    name: str
    command: list[str]
    required: bool


def launch_process(command: list[str], name: str) -> subprocess.Popen:
    print(f"[start] {name}: {' '.join(command)}")
    return subprocess.Popen(command, cwd=str(ROOT))


def stop_processes(processes: list[tuple[str, subprocess.Popen]]) -> None:
    for name, proc in processes:
        if proc.poll() is None:
            print(f"[stop] {name}")
            proc.terminate()
    deadline = time.monotonic() + 5.0
    for name, proc in processes:
        if proc.poll() is None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                print(f"[kill] {name}")
                proc.kill()


def role_commands(role: str, config: str, no_camera: bool, quest_fpv: bool) -> list[ProcessSpec]:
    py = sys.executable
    if role == "pc":
        specs = [
            ProcessSpec("g29_sender", [py, "Client/g29_sender.py", "--config", config], True),
        ]
        if not no_camera and not quest_fpv:
            specs.append(
                ProcessSpec("camera_viewer", [py, "Client/camera_stream_client.py", "--config", config], False)
            )
            specs.append(
                ProcessSpec("camera_servo_ui", [py, "Client/camera_servo_ui.py", "--config", config], False)
            )
        return specs
    if role == "pi":
        specs = [
            ProcessSpec("g29_receiver", [py, "Server/g29_receiver.py", "--config", config], True),
        ]
        if not no_camera:
            if quest_fpv:
                specs.append(
                    ProcessSpec("quest_fpv_server", [py, "Server/quest_fpv_server.py", "--config", config], False)
                )
            else:
                specs.append(
                    ProcessSpec("camera_server", [py, "Server/camera_stream_server.py", "--config", config], False)
                )
                specs.append(
                    ProcessSpec("servo_server", [py, "Server/servo_control_server.py", "--config", config], False)
                )
        return specs
    if role == "all":
        specs = [
            ProcessSpec("g29_receiver", [py, "Server/g29_receiver.py", "--config", config], True),
            ProcessSpec("g29_sender", [py, "Client/g29_sender.py", "--config", config], True),
        ]
        if not no_camera:
            if quest_fpv:
                specs.append(
                    ProcessSpec("quest_fpv_server", [py, "Server/quest_fpv_server.py", "--config", config], False)
                )
            else:
                specs.append(
                    ProcessSpec("camera_server", [py, "Server/camera_stream_server.py", "--config", config], False)
                )
                specs.append(
                    ProcessSpec("servo_server", [py, "Server/servo_control_server.py", "--config", config], False)
                )
                specs.append(
                    ProcessSpec("camera_viewer", [py, "Client/camera_stream_client.py", "--config", config], False)
                )
                specs.append(
                    ProcessSpec("camera_servo_ui", [py, "Client/camera_servo_ui.py", "--config", config], False)
                )
        return specs
    raise ValueError(f"Unsupported role: {role}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Master launcher for G29 drive + camera stream",
    )
    parser.add_argument(
        "--role",
        choices=["pc", "pi", "all"],
        required=True,
        help="pc: sender+viewer, pi: receiver+camera server, all: everything on one machine",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to config json")
    parser.add_argument("--no-camera", action="store_true", help="Skip camera processes")
    parser.add_argument(
        "--quest-fpv",
        action="store_true",
        help="On Pi, run Quest FPV web server instead of PC camera viewer + servo UI stack",
    )
    args = parser.parse_args()

    commands = role_commands(args.role, args.config, args.no_camera, args.quest_fpv)
    processes: list[tuple[ProcessSpec, subprocess.Popen]] = []
    stopping = False

    def handle_signal(sig, frame):  # type: ignore[no-untyped-def]
        nonlocal stopping
        if stopping:
            return
        stopping = True
        print("\nReceived signal, shutting down...")
        stop_processes([(s.name, p) for s, p in processes])

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        for spec in commands:
            processes.append((spec, launch_process(spec.command, spec.name)))

        print(f"Master running in '{args.role}' mode. Press Ctrl+C to stop.")
        while True:
            for spec, proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"[exit] {spec.name} exited with code {code}")
                    if spec.required:
                        stop_processes([(s.name, p) for s, p in processes])
                        sys.exit(code if code != 0 else 0)
                    # Optional process failed: keep required control processes running.
                    if spec.name in {"camera_viewer", "camera_server", "servo_server", "quest_fpv_server"} and code != 0:
                        if spec.name == "camera_viewer":
                            print(
                                "[warn] camera_viewer failed. If cv2 is missing, run: "
                                "python -m pip install opencv-python"
                            )
                        elif spec.name == "quest_fpv_server":
                            print(
                                "[warn] quest_fpv_server failed. Check camera with "
                                "libcamera-hello --list-cameras and I2C with sudo i2cdetect -y 1"
                            )
                        elif spec.name == "servo_server":
                            print(
                                "[warn] servo_server failed. Check I2C/PCA9685 with: "
                                "sudo i2cdetect -y 1"
                            )
                        else:
                            print(
                                "[warn] camera_server failed. Check Pi camera detection with: "
                                "libcamera-hello --list-cameras"
                            )
                    processes = [(s, p) for s, p in processes if p is not proc]
            time.sleep(0.2)
    finally:
        stop_processes([(s.name, p) for s, p in processes])


if __name__ == "__main__":
    main()
