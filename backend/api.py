"""FastAPI REST + WebSocket — docs/09, skills/fastapi-realtime"""

import asyncio
import csv
import io
import logging
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bacnet_engine import BACnetEngine
from .config_store import ConfigStore
from .models import (
    ALWAYS_COMMANDABLE_TYPES,
    MULTISTATE_TYPES,
    READONLY_TYPES,
    BACnetObject,
    ConnectionConfig,
    DeviceConfig,
    ObjectType,
    SimulatorConfig,
)

log = logging.getLogger("api")


# --- Request/response schemas ---

class ObjectCreateRequest(BaseModel):
    type: ObjectType
    instance: int = Field(ge=0)
    name: str
    description: str = ""
    present_value: Any = 0
    units: int = 95
    commandable: bool = False
    relinquish_default: Any = 0
    number_of_states: Optional[int] = None
    state_text: Optional[List[str]] = None
    out_of_service: bool = False


class ObjectUpdateRequest(BaseModel):
    present_value: Optional[Any] = None
    priority: Optional[int] = Field(default=None, ge=1, le=16)
    description: Optional[str] = None
    out_of_service: Optional[bool] = None
    name: Optional[str] = None


class RandomConfigRequest(BaseModel):
    random_enabled: bool
    random_min: Optional[float] = None
    random_max: Optional[float] = None
    random_interval: float = Field(default=5.0, ge=0.5, le=300.0)


class ConfigUpdateRequest(BaseModel):
    connection: Optional[ConnectionConfig] = None
    device: Optional[DeviceConfig] = None


# --- WebSocket manager ---

class WSManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    async def broadcast(self, data: dict):
        dead: List[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)


# --- Build app ---

def create_api(store: ConfigStore, engine: BACnetEngine, event_queue: asyncio.Queue) -> FastAPI:
    app = FastAPI(title="BACnet Simulator API")
    ws_mgr = WSManager()

    # --- Engine start/stop ---

    @app.get("/api/engine/status")
    async def engine_status():
        return {
            "running": engine.running,
            "mstp_status": engine.mstp_status,
        }

    @app.post("/api/engine/start")
    async def engine_start():
        if engine.running:
            return {"status": "already running"}
        try:
            await engine.start()
            return {"status": "started"}
        except Exception as e:
            log.error("engine start failed: %s", e, exc_info=True)
            raise HTTPException(500, f"Failed to start: {e}")

    @app.post("/api/engine/stop")
    async def engine_stop():
        if not engine.running:
            return {"status": "already stopped"}
        await engine.stop()
        return {"status": "stopped"}

    @app.post("/api/shutdown")
    async def shutdown():
        """Shutdown entire application"""
        import os
        log.info("Shutdown requested from UI")
        try:
            if engine.running:
                await engine.stop()
            if store.config:
                store.save_now()
        except Exception:
            pass
        os._exit(0)

    # --- Config endpoints (docs/09) ---

    @app.get("/api/config")
    async def get_config():
        cfg = store.config
        return {
            "connection": cfg.connection.model_dump(),
            "device": cfg.device.model_dump(),
        }

    @app.put("/api/config")
    async def update_config(req: ConfigUpdateRequest):
        cfg = store.config
        needs_rebuild = False

        if req.device:
            cfg.device = req.device

        if req.connection:
            old_conn = cfg.connection
            cfg.connection = req.connection
            if (old_conn.bacnet_ip.port != req.connection.bacnet_ip.port
                    or old_conn.bacnet_ip.interface != req.connection.bacnet_ip.interface
                    or old_conn.bacnet_ip.enabled != req.connection.bacnet_ip.enabled
                    or old_conn.network_number != req.connection.network_number):
                needs_rebuild = True

        store.save_now()

        if needs_rebuild and engine.running:
            try:
                await engine.rebuild()
                return {"status": "applied", "restarted": True}
            except Exception as e:
                log.error("rebuild failed: %s", e)
                raise HTTPException(500, f"Failed to restart BACnet link: {e}")

        return {"status": "applied", "restarted": False}

    # --- Object endpoints (docs/09) ---

    @app.get("/api/objects")
    async def list_objects():
        return [_obj_to_dict(o) for o in store.config.objects]

    @app.post("/api/objects", status_code=201)
    async def create_object(req: ObjectCreateRequest):
        cfg = store.config

        for o in cfg.objects:
            if o.type == req.type and o.instance == req.instance:
                raise HTTPException(409, f"Object {req.type.value}:{req.instance} already exists")

        for o in cfg.objects:
            if o.name == req.name:
                raise HTTPException(409, f"Object name '{req.name}' already in use")

        if req.type in MULTISTATE_TYPES:
            if not req.number_of_states or req.number_of_states < 1:
                raise HTTPException(400, "Multi-state objects require number_of_states >= 1")
            if not req.state_text or len(req.state_text) != req.number_of_states:
                raise HTTPException(400, "state_text length must match number_of_states")

        obj_cfg = BACnetObject(
            type=req.type,
            instance=req.instance,
            name=req.name,
            description=req.description,
            present_value=req.present_value,
            units=req.units,
            commandable=req.commandable,
            relinquish_default=req.relinquish_default,
            number_of_states=req.number_of_states,
            state_text=req.state_text,
            out_of_service=req.out_of_service,
        )

        cfg.objects.append(obj_cfg)

        if engine.running:
            try:
                await engine.add_object_from_config(obj_cfg)
            except Exception as e:
                cfg.objects.remove(obj_cfg)
                raise HTTPException(500, f"Failed to create BACnet object: {e}")

        store.save_soon()

        await ws_mgr.broadcast({
            "event": "object_added",
            "object": _obj_to_dict(obj_cfg),
        })

        return _obj_to_dict(obj_cfg)

    @app.put("/api/objects/{obj_type}/{instance}")
    async def update_object(obj_type: str, instance: int, req: ObjectUpdateRequest):
        ot = _parse_object_type(obj_type)
        cfg = store.config

        cfg_obj = _find_config_object(cfg, ot, instance)
        if not cfg_obj:
            raise HTTPException(404, f"Object {obj_type}:{instance} not found")

        if req.description is not None:
            cfg_obj.description = req.description

        if req.out_of_service is not None:
            cfg_obj.out_of_service = req.out_of_service
            bp_obj = engine.get_object(ot, instance)
            if bp_obj:
                bp_obj.outOfService = req.out_of_service

        if req.name is not None and req.name != cfg_obj.name:
            for o in cfg.objects:
                if o.name == req.name:
                    raise HTTPException(409, f"Object name '{req.name}' already in use")
            cfg_obj.name = req.name

        if req.present_value is not None:
            if engine.running:
                try:
                    await engine.set_present_value(ot, instance, req.present_value, req.priority)
                except ValueError as e:
                    raise HTTPException(400, str(e))
            cfg_obj.present_value = req.present_value

        store.save_soon()
        return _obj_to_dict(cfg_obj)

    @app.delete("/api/objects/{obj_type}/{instance}")
    async def delete_object(obj_type: str, instance: int):
        ot = _parse_object_type(obj_type)
        cfg = store.config

        cfg_obj = _find_config_object(cfg, ot, instance)
        if not cfg_obj:
            raise HTTPException(404, f"Object {obj_type}:{instance} not found")

        if engine.running:
            engine.remove_object(ot, instance)
        cfg.objects.remove(cfg_obj)
        store.save_soon()

        await ws_mgr.broadcast({
            "event": "object_removed",
            "type": ot.value,
            "instance": instance,
        })

        return {"status": "deleted"}

    # --- Priority array write ---

    class PriorityWriteRequest(BaseModel):
        slot: int = Field(ge=1, le=16)
        value: Optional[Any] = None  # None = relinquish (NULL)

    @app.put("/api/objects/{obj_type}/{instance}/priority")
    async def write_priority_slot(obj_type: str, instance: int, req: PriorityWriteRequest):
        ot = _parse_object_type(obj_type)
        cfg_obj = _find_config_object(store.config, ot, instance)
        if not cfg_obj:
            raise HTTPException(404, f"Object {obj_type}:{instance} not found")
        if not cfg_obj.commandable:
            raise HTTPException(400, "Object is not commandable")

        if engine.running:
            try:
                await engine.set_present_value(ot, instance, req.value, priority=req.slot)
            except ValueError as e:
                raise HTTPException(400, str(e))

        # sync config
        cfg_obj = _find_config_object(store.config, ot, instance)
        store.save_soon()

        return {
            "present_value": cfg_obj.present_value,
            "priority_array": cfg_obj.priority_array,
        }

    # --- Random simulation config ---

    @app.put("/api/objects/{obj_type}/{instance}/random")
    async def set_random_config(obj_type: str, instance: int, req: RandomConfigRequest):
        ot = _parse_object_type(obj_type)
        cfg_obj = _find_config_object(store.config, ot, instance)
        if not cfg_obj:
            raise HTTPException(404, f"Object {obj_type}:{instance} not found")

        cfg_obj.random_enabled = req.random_enabled
        cfg_obj.random_min = req.random_min
        cfg_obj.random_max = req.random_max
        cfg_obj.random_interval = req.random_interval
        store.save_soon()

        await ws_mgr.broadcast({
            "event": "random_config",
            "type": ot.value,
            "instance": instance,
            "random_enabled": req.random_enabled,
            "random_min": req.random_min,
            "random_max": req.random_max,
            "random_interval": req.random_interval,
        })

        return {"status": "ok"}

    # --- CSV Export/Import ---

    @app.get("/api/export/csv")
    async def export_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "type", "instance", "name", "description", "present_value",
            "units", "commandable", "relinquish_default",
            "number_of_states", "state_text",
            "out_of_service", "random_enabled", "random_min", "random_max", "random_interval",
        ])
        for o in store.config.objects:
            writer.writerow([
                o.type.value, o.instance, o.name, o.description, o.present_value,
                o.units, o.commandable, o.relinquish_default,
                o.number_of_states or "",
                "|".join(o.state_text) if o.state_text else "",
                o.out_of_service,
                o.random_enabled, o.random_min if o.random_min is not None else "",
                o.random_max if o.random_max is not None else "",
                o.random_interval,
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=bacnet_points.csv"},
        )

    @app.post("/api/import/csv")
    async def import_csv(file: UploadFile, mode: str = "overwrite"):
        """mode: 'skip' | 'overwrite' | 'replace'"""
        content = await file.read()
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        # replace = ลบทั้งหมดก่อน
        if mode == "replace":
            if engine.running:
                for o in list(store.config.objects):
                    engine.remove_object(o.type, o.instance)
            store.config.objects.clear()

        imported = 0
        updated = 0
        errors = []
        for i, row in enumerate(reader, start=2):
            try:
                obj_type = ObjectType(row["type"])
                instance = int(row["instance"])

                state_text = row.get("state_text", "").split("|") if row.get("state_text") else None
                if state_text:
                    state_text = [s.strip() for s in state_text if s.strip()]

                pv = row.get("present_value", "0")
                try:
                    pv = float(pv) if "." in str(pv) else int(pv)
                except (ValueError, TypeError):
                    pass

                rd = row.get("relinquish_default", "0")
                try:
                    rd = float(rd) if "." in str(rd) else int(rd)
                except (ValueError, TypeError):
                    rd = 0

                nos = row.get("number_of_states", "")
                nos = int(nos) if nos and nos.strip() else None

                obj_cfg = BACnetObject(
                    type=obj_type,
                    instance=instance,
                    name=row.get("name", f"{row['type']}:{instance}"),
                    description=row.get("description", ""),
                    present_value=pv,
                    units=int(row.get("units", 95)),
                    commandable=row.get("commandable", "").lower() in ("true", "1", "yes"),
                    relinquish_default=rd,
                    number_of_states=nos,
                    state_text=state_text if state_text else None,
                    out_of_service=row.get("out_of_service", "").lower() in ("true", "1", "yes"),
                    random_enabled=row.get("random_enabled", "").lower() in ("true", "1", "yes"),
                    random_min=float(row["random_min"]) if row.get("random_min", "").strip() else None,
                    random_max=float(row["random_max"]) if row.get("random_max", "").strip() else None,
                    random_interval=float(row.get("random_interval", 5.0) or 5.0),
                )

                existing = _find_config_object(store.config, obj_type, instance)
                if existing:
                    if mode == "skip":
                        errors.append(f"Row {i}: {row['type']}:{instance} already exists, skipped")
                        continue
                    # overwrite: ลบตัวเก่า แล้วเพิ่มตัวใหม่
                    if engine.running:
                        engine.remove_object(obj_type, instance)
                    store.config.objects.remove(existing)
                    updated += 1
                else:
                    imported += 1

                store.config.objects.append(obj_cfg)
                if engine.running:
                    try:
                        await engine.add_object_from_config(obj_cfg)
                    except Exception:
                        pass
            except Exception as e:
                errors.append(f"Row {i}: {e}")

        store.save_now()

        await ws_mgr.broadcast({
            "event": "snapshot",
            "objects": [_obj_to_dict(o) for o in store.config.objects],
        })

        return {"imported": imported, "updated": updated, "errors": errors}

    # --- Interfaces endpoint (docs/05) ---

    @app.get("/api/interfaces")
    async def list_interfaces():
        import socket
        results = [{"label": "Auto-detect", "value": "auto"}]
        try:
            import psutil
            for name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        mask = addr.netmask or "255.255.255.0"
                        bits = sum(bin(int(x)).count("1") for x in mask.split("."))
                        results.append({
                            "label": f"{name} — {addr.address}/{bits}",
                            "value": f"{addr.address}/{bits}",
                        })
        except ImportError:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                results.append({"label": f"Default — {ip}/24", "value": f"{ip}/24"})
            finally:
                s.close()
        results.append({"label": "Loopback (testing only)", "value": "127.0.0.1/32"})
        return results

    # --- Serial ports endpoint (docs/06) ---

    @app.get("/api/serial-ports")
    async def list_serial_ports():
        try:
            from serial.tools.list_ports import comports
            return [{"port": p.device, "description": p.description} for p in comports()]
        except ImportError:
            return []

    # --- WebSocket (skills/fastapi-realtime) ---

    @app.websocket("/api/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_mgr.connect(ws)
        try:
            snapshot = [_obj_to_dict(o) for o in store.config.objects]
            await ws.send_json({"event": "snapshot", "objects": snapshot, "running": engine.running})

            while True:
                try:
                    await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                except asyncio.TimeoutError:
                    await ws.send_json({"event": "ping"})
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            ws_mgr.disconnect(ws)

    # --- Event broadcaster task ---

    async def _broadcast_events():
        while True:
            event = await event_queue.get()
            await ws_mgr.broadcast(event)

    @app.on_event("startup")
    async def startup():
        asyncio.create_task(_broadcast_events())

    # --- Static files (frontend) — mount LAST after /api routes ---
    import os, sys
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(__file__)))
    frontend_dir = os.path.join(base, "frontend")
    if os.path.isdir(frontend_dir):
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


# --- Helpers ---

def _parse_object_type(s: str) -> ObjectType:
    try:
        return ObjectType(s)
    except ValueError:
        raise HTTPException(400, f"Invalid object type: {s}")


def _find_config_object(cfg: SimulatorConfig, ot: ObjectType, instance: int):
    for o in cfg.objects:
        if o.type == ot and o.instance == instance:
            return o
    return None


def _obj_to_dict(o: BACnetObject) -> dict:
    d = o.model_dump()
    d["type"] = o.type.value
    return d
