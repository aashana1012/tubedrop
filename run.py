"""Start TubeDrop: python run.py [--no-browser] [--port 8756]"""
from __future__ import annotations

import argparse
import json
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT_RANGE = 20


def running_copy(preferred: int) -> int | None:
    """Return the port of a TubeDrop that is already running, if there is one.

    Two copies would share one download folder and one history file and trip over
    each other, so a second start just opens the first copy instead.
    """
    for port in range(preferred, preferred + PORT_RANGE):
        if port_is_free(port):
            continue  # nothing is listening here, so there is nothing to ask
        try:
            with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=2) as response:
                if response.status == 200 and "ytdlp_version" in json.loads(response.read()):
                    return port
        except (OSError, ValueError):
            continue
    return None


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def free_port(preferred: int) -> int:
    for port in range(preferred, preferred + PORT_RANGE):
        if port_is_free(port):
            return port
    raise SystemExit("No free port found. Close other programs using ports 8756 and up, then try again.")


def main() -> None:
    parser = argparse.ArgumentParser(description="TubeDrop - YouTube and Instagram downloader dashboard")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    existing = running_copy(args.port)
    if existing is not None:
        url = f"http://{HOST}:{existing}"
        print(f"\n  TubeDrop is already running at {url}\n  Opening that one instead of starting a second copy.\n")
        if not args.no_browser:
            webbrowser.open(url)
            time.sleep(3)  # leave the message on screen long enough to read
        return

    port = free_port(args.port)
    url = f"http://{HOST}:{port}"
    print(f"\n  TubeDrop is running at {url}\n  Keep this window open. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run("app.server:app", host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
