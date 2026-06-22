"""Entry point — skills/pywebview-desktop + skills/fastapi-realtime

Architecture (docs/09):
  MAIN THREAD:   pywebview window (blocking)
  DAEMON THREAD: asyncio event loop → FastAPI + bacpypes3
"""

import asyncio
import logging
import os
import sys
import threading
import traceback

import uvicorn

from .api import create_api
from .bacnet_engine import BACnetEngine
from .config_store import ConfigStore


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    if getattr(sys, 'frozen', False):
        log_path = os.path.join(os.path.dirname(sys.executable), "simulator.log")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
        logging.getLogger().addHandler(fh)


_setup_logging()
log = logging.getLogger("main")

API_HOST = "127.0.0.1"
API_PORT = 8736

_loop: asyncio.AbstractEventLoop = None
_server: uvicorn.Server = None


async def _run_backend(store, engine, event_queue, ready_event: threading.Event):
    global _loop, _server
    _loop = asyncio.get_running_loop()

    app = create_api(store, engine, event_queue)
    uvi_kwargs = {"app": app, "host": API_HOST, "port": API_PORT, "log_level": "info"}
    if getattr(sys, 'frozen', False):
        uvi_kwargs["log_config"] = None
    config = uvicorn.Config(**uvi_kwargs)
    _server = uvicorn.Server(config)

    log.info("Starting API at http://%s:%d", API_HOST, API_PORT)
    ready_event.set()

    try:
        await _server.serve()
    except asyncio.CancelledError:
        pass
    finally:
        store.save_now()
        await engine.stop()
        log.info("Backend shutdown complete")


def _backend_thread(store, engine, event_queue, ready_event: threading.Event):
    try:
        asyncio.run(_run_backend(store, engine, event_queue, ready_event))
    except Exception as e:
        log.error("Backend thread crashed: %s", e)
        log.error(traceback.format_exc())


def _shutdown_backend():
    """สั่ง uvicorn หยุดจาก main thread อย่างนุ่มนวล"""
    if _server:
        _server.should_exit = True


def main():
    store = ConfigStore()
    event_queue = asyncio.Queue(maxsize=1000)
    engine = BACnetEngine(store, event_queue)

    if "--no-gui" in sys.argv:
        # No-GUI mode: รัน asyncio ใน main thread ตรงๆ — uvicorn จัดการ Ctrl+C เอง
        try:
            asyncio.run(_run_backend(store, engine, event_queue, threading.Event()))
        except KeyboardInterrupt:
            log.info("Interrupted")
        return

    # GUI mode: backend ใน daemon thread, pywebview ใน main thread
    ready_event = threading.Event()
    t = threading.Thread(
        target=_backend_thread,
        args=(store, engine, event_queue, ready_event),
        daemon=True,
    )
    t.start()

    from .desktop import open_window
    open_window(API_PORT, on_closed=_shutdown_backend)

    t.join(timeout=5)
    log.info("Exiting")


if __name__ == "__main__":
    main()
