import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = str(ROOT / "g29_control" / "config.json")


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


def role_commands(role: str, config: str) -> list[tuple[str, list[str]]]:
    py = sys.executable
    if role == "pc":
        return [
            ("g29_sender", [py, "Client/g29_sender.py", "--config", config]),
            ("camera_viewer", [py, "Client/camera_stream_client.py", "--config", config]),
        ]
    if role == "pi":
        return [
            ("g29_receiver", [py, "Server/g29_receiver.py", "--config", config]),
            ("camera_server", [py, "Server/camera_stream_server.py", "--config", config]),
        ]
    if role == "all":
        return [
            ("g29_receiver", [py, "Server/g29_receiver.py", "--config", config]),
            ("camera_server", [py, "Server/camera_stream_server.py", "--config", config]),
            ("g29_sender", [py, "Client/g29_sender.py", "--config", config]),
            ("camera_viewer", [py, "Client/camera_stream_client.py", "--config", config]),
        ]
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
    args = parser.parse_args()

    commands = role_commands(args.role, args.config)
    processes: list[tuple[str, subprocess.Popen]] = []
    stopping = False

    def handle_signal(sig, frame):  # type: ignore[no-untyped-def]
        nonlocal stopping
        if stopping:
            return
        stopping = True
        print("\nReceived signal, shutting down...")
        stop_processes(processes)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        for name, cmd in commands:
            processes.append((name, launch_process(cmd, name)))

        print(f"Master running in '{args.role}' mode. Press Ctrl+C to stop.")
        while True:
            for name, proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"[exit] {name} exited with code {code}")
                    stop_processes(processes)
                    sys.exit(code if code != 0 else 0)
            time.sleep(0.2)
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    main()
