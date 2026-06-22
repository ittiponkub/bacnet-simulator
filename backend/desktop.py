"""pywebview desktop window — skills/pywebview-desktop"""

import logging
import os
import sys
import traceback

import webview

log = logging.getLogger("desktop")

LOG_FILE = None


def _setup_file_log():
    """เขียน log ลงไฟล์ข้าง exe เพื่อ debug กรณี crash"""
    global LOG_FILE
    if getattr(sys, 'frozen', False):
        log_path = os.path.join(os.path.dirname(sys.executable), "simulator.log")
    else:
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "simulator.log")
    LOG_FILE = log_path
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logging.getLogger().addHandler(fh)
    log.info("Log file: %s", log_path)


def open_window(port: int, on_closed=None):
    _setup_file_log()

    url = f"http://127.0.0.1:{port}"

    loading_url = f"{url}/loading.html"
    log.info("Opening window with loading screen")
    try:
        window = webview.create_window(
            "BACnet Simulator",
            loading_url,
            width=1340,
            height=860,
            min_size=(1024, 680),
            background_color="#0B0F1A",
        )
        webview.start(debug=False)
        log.info("Window closed normally")
    except Exception as e:
        log.error("pywebview error: %s", e)
        log.error(traceback.format_exc())

    if on_closed:
        on_closed()
