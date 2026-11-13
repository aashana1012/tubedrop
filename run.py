"""Start TubeDrop: python run.py [--no-browser] [--port 8756]"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"


def free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found. Close other copies of TubeDrop and try again.")


def main() -> None:
    parser = argparse.ArgumentParser(description="TubeDrop - YouTube to MP3 / MP4 dashboard")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    port = free_port(args.port)
    url = f"http://{HOST}:{port}"
    print(f"\n  TubeDrop is running at {url}\n  Keep this window open. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run("app.server:app", host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
