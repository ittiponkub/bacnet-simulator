"""BACnet Application engine — สร้าง/จัดการ device, objects, IP link — docs/04, docs/05, docs/07"""

import asyncio
import logging
import random
import socket
from typing import Any, Callable, Dict, List, Optional, Tuple

from bacpypes3.app import Application
from bacpypes3.basetypes import PriorityValue
from bacpypes3.errors import ExecutionError
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.object import DeviceObject
from bacpypes3.pdu import Address

from .config_store import ConfigStore
from .models import (
    ALWAYS_COMMANDABLE_TYPES,
    MULTISTATE_TYPES,
    ObjectType,
    READONLY_TYPES,
    SimulatorConfig,
)
from .object_factory import _BINARY_TYPES, _make_priority_value, create_bacpypes_object

log = logging.getLogger("bacnet_engine")


def _resolve_interface(interface: str, port: int) -> str:
    """Resolve 'auto' interface to actual IP/CIDR:port — docs/05"""
    if interface == "auto":
        try:
            import psutil
            for _name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        if addr.netmask:
                            bits = sum(bin(int(x)).count("1") for x in addr.netmask.split("."))
                            return f"{addr.address}/{bits}:{port}"
        except ImportError:
            pass
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return f"{ip}/24:{port}"

    if "/" not in interface:
        return f"{interface}/24:{port}"
    if ":" not in interface:
        return f"{interface}:{port}"
    return interface


ANALOG_TYPES = {ObjectType.analogInput, ObjectType.analogOutput, ObjectType.analogValue}


class BACnetEngine:
    def __init__(self, store: ConfigStore, event_queue: asyncio.Queue):
        self._store = store
        self._event_queue = event_queue
        self._app: Optional[Application] = None
        self._objects: Dict[Tuple[ObjectType, int], Any] = {}
        self._running = False
        self._random_task: Optional[asyncio.Task] = None

    @property
    def app(self) -> Optional[Application]:
        return self._app

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        cfg = self._store.config
        await self._build_application(cfg)
        self._running = True
        self._start_random_task()
        log.info(
            "BACnet engine started — device %s (%d), %d objects",
            cfg.device.name, cfg.device.instance, len(self._objects),
        )
        self._notify_status()

    async def stop(self) -> None:
        self._stop_random_task()
        if self._app:
            result = self._app.close()
            if result is not None:
                await result
            self._app = None
            self._objects.clear()
        self._running = False
        log.info("BACnet engine stopped")
        self._notify_status()

    async def rebuild(self) -> None:
        await self.stop()
        await self.start()

    @property
    def mstp_status(self) -> str:
        return getattr(self, "_mstp_status", "disabled")

    @staticmethod
    def _get_bacpypes_version() -> str:
        try:
            import bacpypes3
            return bacpypes3.__version__
        except Exception:
            return "unknown"

    def _notify_mstp_status(self) -> None:
        try:
            self._event_queue.put_nowait({
                "event": "mstp_status",
                "status": self._mstp_status,
                "message": "MS/TP is not supported in the current bacpypes3 version. "
                           "Config is saved and will be used when support is available.",
            })
        except asyncio.QueueFull:
            pass

    def _notify_status(self) -> None:
        try:
            self._event_queue.put_nowait({
                "event": "engine_status",
                "running": self._running,
            })
        except asyncio.QueueFull:
            pass

    # --- Random simulation ---

    def _start_random_task(self) -> None:
        self._stop_random_task()
        self._random_task = asyncio.create_task(self._random_loop())

    def _stop_random_task(self) -> None:
        if self._random_task and not self._random_task.done():
            self._random_task.cancel()
        self._random_task = None

    async def _random_loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(1.0)
                now = asyncio.get_event_loop().time()
                for cfg_obj in self._store.config.objects:
                    if not cfg_obj.random_enabled:
                        continue
                    if cfg_obj.type not in ANALOG_TYPES:
                        continue
                    rmin = cfg_obj.random_min if cfg_obj.random_min is not None else 0.0
                    rmax = cfg_obj.random_max if cfg_obj.random_max is not None else 100.0
                    new_val = round(random.uniform(rmin, rmax), 2)
                    try:
                        await self.set_present_value(cfg_obj.type, cfg_obj.instance, new_val)
                    except Exception:
                        pass
                    await asyncio.sleep(max(0.05, cfg_obj.random_interval - 1.0))
        except asyncio.CancelledError:
            pass

    # --- Application construction ---

    async def _build_application(self, cfg: SimulatorConfig) -> None:
        dev = DeviceObject(
            objectIdentifier=("device", cfg.device.instance),
            objectName=cfg.device.name,
            vendorIdentifier=cfg.device.vendor_id,
            vendorName=cfg.device.vendor_name,
            modelName="BACnet Simulator",
            firmwareRevision="1.0",
            applicationSoftwareVersion="1.0",
            protocolVersion=1,
            protocolRevision=22,
            maxApduLengthAccepted=cfg.connection.bacnet_ip.max_apdu_length,
            segmentationSupported="segmented-both",
            apduTimeout=cfg.connection.bacnet_ip.apdu_timeout_ms,
            numberOfApduRetries=cfg.connection.bacnet_ip.apdu_retries,
            databaseRevision=1,
        )

        objects_list: List[Any] = [dev]

        if cfg.connection.bacnet_ip.enabled:
            addr_str = _resolve_interface(
                cfg.connection.bacnet_ip.interface,
                cfg.connection.bacnet_ip.port,
            )
            log.info("BACnet/IP address: %s", addr_str)
            npo = NetworkPortObject(
                addr_str,
                objectIdentifier=("network-port", 1),
                objectName="NetworkPort-1",
            )
            if cfg.connection.network_number:
                npo.networkNumber = cfg.connection.network_number
                npo.networkNumberQuality = "configured"
            objects_list.append(npo)

        # MS/TP — docs/06: bacpypes3 0.0.106 ยังไม่มี MS/TP link layer
        if cfg.connection.mstp.enabled:
            self._mstp_status = "unsupported"
            log.warning(
                "MS/TP enabled in config but bacpypes3 %s does not have MS/TP link layer. "
                "MS/TP will not be active. Config is saved for future use.",
                self._get_bacpypes_version(),
            )
            self._notify_mstp_status()
        else:
            self._mstp_status = "disabled"

        if not cfg.connection.bacnet_ip.enabled and cfg.connection.mstp.enabled:
            raise RuntimeError(
                "Cannot start: BACnet/IP is disabled and MS/TP is not yet supported "
                f"in bacpypes3 {self._get_bacpypes_version()}. Enable BACnet/IP to continue."
            )

        if not cfg.connection.bacnet_ip.enabled and not cfg.connection.mstp.enabled:
            raise RuntimeError("Cannot start: both BACnet/IP and MS/TP are disabled.")

        app = Application.from_object_list(objects_list)

        # override write handler to enforce commandable/read-only — docs/04, docs/07
        original_do_write = app.do_WritePropertyRequest

        async def custom_write_handler(apdu):
            await self._handle_write(apdu, original_do_write)

        app.do_WritePropertyRequest = custom_write_handler

        self._app = app

        for obj_cfg in cfg.objects:
            await self.add_object_from_config(obj_cfg, save=False)

    # --- Object management ---

    async def add_object_from_config(self, obj_cfg, save: bool = True) -> Any:
        bp_obj = create_bacpypes_object(obj_cfg)
        self._app.add_object(bp_obj)
        self._objects[(obj_cfg.type, obj_cfg.instance)] = bp_obj
        self._update_object_list()
        if save:
            self._store.save_soon()
        return bp_obj

    def remove_object(self, obj_type: ObjectType, instance: int) -> None:
        key = (obj_type, instance)
        bp_obj = self._objects.pop(key, None)
        if bp_obj and self._app:
            self._app.delete_object(bp_obj)
            self._update_object_list()

    def _update_object_list(self) -> None:
        if not self._app or not self._app.device_object:
            return
        obj_list = list(self._app.objectIdentifier.keys())
        self._app.device_object.objectList = obj_list
        self._store.save_soon()

    def get_object(self, obj_type: ObjectType, instance: int) -> Optional[Any]:
        return self._objects.get((obj_type, instance))

    # --- Write handler — commandable + read-only enforcement (docs/04, docs/07) ---

    async def _handle_write(self, apdu, original_handler) -> None:
        from bacpypes3.apdu import SimpleAckPDU

        obj = self._app.get_object_id(apdu.objectIdentifier)
        if not obj:
            raise ExecutionError(errorClass="object", errorCode="unknownObject")

        prop_id = apdu.propertyIdentifier
        priority = apdu.priority

        # only intercept presentValue writes
        if prop_id != "presentValue" and prop_id != 85:
            await original_handler(apdu)
            return

        sim_type = getattr(obj, "_sim_type", None)
        is_commandable = getattr(obj, "_sim_commandable", False)
        out_of_service = getattr(obj, "outOfService", False)

        # AI/BI/MSI: read-only unless out-of-service — docs/04 rule 1
        if sim_type in READONLY_TYPES and not out_of_service:
            raise ExecutionError(errorClass="property", errorCode="writeAccessDenied")

        if is_commandable:
            await self._write_commandable(obj, apdu, priority)
        else:
            # non-commandable writable object (AV not commandable, or out-of-service input)
            await original_handler(apdu)
            self._notify_value_change(obj, "bacnet")

    async def _write_commandable(self, obj, apdu, priority: Optional[int]) -> None:
        """Handle write to commandable object via priority array — docs/04"""
        from bacpypes3.apdu import SimpleAckPDU

        sim_type = obj._sim_type
        prop_type = obj.get_property_type(apdu.propertyIdentifier)
        property_value = apdu.propertyValue.cast_out(prop_type, null=(priority is not None))

        if priority is None:
            # docs/04: no priority on commandable → use slot 16 for compatibility
            priority = 16

        if priority < 1 or priority > 16:
            raise ExecutionError(errorClass="property", errorCode="invalidArrayIndex")

        pa = obj.priorityArray

        if property_value is None or (hasattr(property_value, 'is_null') and property_value.is_null):
            # relinquish — docs/04: write Null to slot
            pa[priority - 1] = PriorityValue(null=())
        else:
            pa[priority - 1] = _make_priority_value(sim_type, property_value)

        obj.priorityArray = pa

        # recalculate presentValue from highest priority non-null slot
        new_pv = self._calc_present_value(obj)
        obj.presentValue = new_pv

        # update config
        self._sync_object_to_config(obj, pa)

        resp = SimpleAckPDU(context=apdu)
        await self._app.response(resp)

        self._notify_value_change(obj, "bacnet")

    def _calc_present_value(self, obj) -> Any:
        """Calculate effective PV from priority array — docs/04"""
        pa = obj.priorityArray
        for slot in pa:
            choice = getattr(slot, "_choice", None)
            if choice and choice != "null":
                return getattr(slot, choice)
        # all null → use relinquish default
        return obj.relinquishDefault

    def _sync_object_to_config(self, obj, pa) -> None:
        """Sync bacpypes3 object state back to config store."""
        sim_type = obj._sim_type
        obj_id = obj.objectIdentifier
        instance = obj_id[1]

        for cfg_obj in self._store.config.objects:
            if cfg_obj.type == sim_type and cfg_obj.instance == instance:
                pv = obj.presentValue
                if sim_type in _BINARY_TYPES:
                    cfg_obj.present_value = 1 if str(pv) == "active" else 0
                else:
                    cfg_obj.present_value = pv

                cfg_obj.priority_array = []
                for slot in pa:
                    choice = getattr(slot, "_choice", None)
                    if choice and choice != "null":
                        val = getattr(slot, choice)
                        if sim_type in _BINARY_TYPES:
                            cfg_obj.priority_array.append(1 if val else 0)
                        else:
                            cfg_obj.priority_array.append(val)
                    else:
                        cfg_obj.priority_array.append(None)
                break

        self._store.save_soon()

    # --- Value updates from UI ---

    async def set_present_value(self, obj_type: ObjectType, instance: int, value: Any,
                                priority: Optional[int] = None) -> None:
        """Set present value from UI/API side."""
        bp_obj = self._objects.get((obj_type, instance))
        if not bp_obj:
            raise ValueError(f"object not found: {obj_type}:{instance}")

        is_commandable = getattr(bp_obj, "_sim_commandable", False)

        if is_commandable and priority is not None:
            pa = bp_obj.priorityArray
            if value is None:
                pa[priority - 1] = PriorityValue(null=())
            else:
                pa[priority - 1] = _make_priority_value(obj_type, value)
            bp_obj.priorityArray = pa
            new_pv = self._calc_present_value(bp_obj)
            bp_obj.presentValue = new_pv
            self._sync_object_to_config(bp_obj, pa)
        else:
            if obj_type in _BINARY_TYPES:
                bp_obj.presentValue = "active" if value else "inactive"
            else:
                bp_obj.presentValue = value
            # sync to config
            for cfg_obj in self._store.config.objects:
                if cfg_obj.type == obj_type and cfg_obj.instance == instance:
                    cfg_obj.present_value = value
                    break
            self._store.save_soon()

        self._notify_value_change(bp_obj, "ui")

    def _notify_value_change(self, obj, source: str) -> None:
        """Push value change event to WebSocket queue."""
        sim_type = getattr(obj, "_sim_type", None)
        obj_id = obj.objectIdentifier
        pv = obj.presentValue

        if sim_type in _BINARY_TYPES:
            pv = 1 if str(pv) == "active" else 0

        event = {
            "event": "value_change",
            "type": sim_type.value if sim_type else str(obj_id[0]),
            "instance": obj_id[1],
            "property": "presentValue",
            "value": pv,
            "source": source,
        }
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("event queue full, dropping event")
