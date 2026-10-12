"""Mac app launcher: runs the web app on 127.0.0.1 in the background and shows it in a native window.

Data lives in ~/Library/Application Support/NBA Stats, so replacing the app with a new version
keeps it. Logs go to ~/Library/Logs/NBA Stats.log. Closing the window quits the app.
"""
import logging
import os
import socket
import threading
import time
from pathlib import Path

APP_NAME = "NBA Stats"
SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
LOG_FILE = Path.home() / "Library" / "Logs" / f"{APP_NAME}.log"

ALREADY_RUNNING = """
<body style="font: 15px/1.5 -apple-system, sans-serif; padding: 32px; color-scheme: light dark">
  <h2 style="margin-top: 0">NBA Stats is already open</h2>
  <p>Another copy of the app (or its developer server, ./run.sh) is using port {port}.
     Quit it first, then open the app again.</p>
</body>
"""


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_server(port: int, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline and not _port_in_use(port):
        time.sleep(0.1)


def main() -> None:
    # Before the app modules load: config reads DATA_DIR at import.
    os.environ.setdefault("DATA_DIR", str(SUPPORT_DIR))
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    import webview
    from app import config

    if _port_in_use(config.PORT):
        webview.create_window(APP_NAME, html=ALREADY_RUNNING.format(port=config.PORT), width=520, height=260)
        webview.start()
        return

    import uvicorn
    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.PORT, loop="asyncio", http="h11",
                                           lifespan="on", log_config=None))
    threading.Thread(target=server.run, daemon=True, name="server").start()
    _wait_for_server(config.PORT)

    webview.create_window(APP_NAME, f"http://127.0.0.1:{config.PORT}/", width=1280, height=860, min_size=(420, 520))
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
