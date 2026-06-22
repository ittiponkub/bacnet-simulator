"""Load / save devices.json with default seed from docs/08-device-profile"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .models import (
    BACnetIPConfig,
    BACnetObject,
    ConnectionConfig,
    DeviceConfig,
    MSTPConfig,
    ObjectType,
    SimulatorConfig,
)

def _get_config_dir() -> Path:
    import sys
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "config"
    return Path(__file__).resolve().parent.parent / "config"

CONFIG_DIR = _get_config_dir()
CONFIG_FILE = CONFIG_DIR / "devices.json"

_SAVE_DELAY = 1.0  # debounce seconds


def _default_seed() -> SimulatorConfig:
    """Seed data from docs/08-device-profile.md"""
    objects = [
        # --- Analog Input (read-only sensors) ---
        BACnetObject(type=ObjectType.analogInput, instance=0, name="AHU1.SupplyAirTemp",
                     description="AHU-1 supply air temperature", present_value=18.5, units=62),
        BACnetObject(type=ObjectType.analogInput, instance=1, name="AHU1.ReturnAirTemp",
                     description="AHU-1 return air temperature", present_value=23.2, units=62),
        BACnetObject(type=ObjectType.analogInput, instance=2, name="Chiller1.ChWSupplyTemp",
                     description="Chiller-1 chilled water supply temp", present_value=7.0, units=62),
        BACnetObject(type=ObjectType.analogInput, instance=3, name="Zone1.Humidity",
                     description="Zone-1 relative humidity", present_value=55.0, units=29),
        BACnetObject(type=ObjectType.analogInput, instance=4, name="Building.TotalPower",
                     description="Building total electrical power", present_value=142.6, units=48),
        # --- Analog Output (commandable) ---
        BACnetObject(type=ObjectType.analogOutput, instance=0, name="AHU1.SupplyFanSpeed",
                     description="AHU-1 supply fan speed command", present_value=0.0,
                     relinquish_default=0.0, units=98),
        BACnetObject(type=ObjectType.analogOutput, instance=1, name="AHU1.CoolingValve",
                     description="AHU-1 cooling valve position", present_value=0.0,
                     relinquish_default=0.0, units=98),
        BACnetObject(type=ObjectType.analogOutput, instance=2, name="AHU1.HeatingValve",
                     description="AHU-1 heating valve position", present_value=0.0,
                     relinquish_default=0.0, units=98),
        BACnetObject(type=ObjectType.analogOutput, instance=3, name="VAV1.DamperPosition",
                     description="VAV-1 damper position", present_value=50.0,
                     relinquish_default=50.0, units=98),
        BACnetObject(type=ObjectType.analogOutput, instance=4, name="Pump1.SpeedCommand",
                     description="Pump-1 VFD speed command", present_value=0.0,
                     relinquish_default=0.0, units=98),
        # --- Analog Value (setpoints, not commandable) ---
        BACnetObject(type=ObjectType.analogValue, instance=0, name="AHU1.SupplyAirTempSetpoint",
                     description="AHU-1 supply air temp setpoint", present_value=16.0, units=62,
                     commandable=False),
        BACnetObject(type=ObjectType.analogValue, instance=1, name="Zone1.TempSetpoint",
                     description="Zone-1 temperature setpoint", present_value=22.5, units=62,
                     commandable=False),
        BACnetObject(type=ObjectType.analogValue, instance=2, name="Zone2.TempSetpoint",
                     description="Zone-2 temperature setpoint", present_value=23.0, units=62,
                     commandable=False),
        BACnetObject(type=ObjectType.analogValue, instance=3, name="Chiller1.ChWSetpoint",
                     description="Chiller-1 chilled water setpoint", present_value=6.5, units=62,
                     commandable=False),
        BACnetObject(type=ObjectType.analogValue, instance=4, name="Building.DemandLimit",
                     description="Building demand limit setpoint", present_value=200.0, units=48,
                     commandable=False),
        # --- Binary Input (read-only status) ---
        BACnetObject(type=ObjectType.binaryInput, instance=0, name="AHU1.SupplyFanStatus",
                     description="AHU-1 supply fan run status", present_value=1),
        BACnetObject(type=ObjectType.binaryInput, instance=1, name="AHU1.FilterStatus",
                     description="AHU-1 filter dirty (1=dirty)", present_value=0),
        BACnetObject(type=ObjectType.binaryInput, instance=2, name="Chiller1.RunStatus",
                     description="Chiller-1 run status", present_value=1),
        BACnetObject(type=ObjectType.binaryInput, instance=3, name="Pump1.RunStatus",
                     description="Pump-1 run status", present_value=1),
        BACnetObject(type=ObjectType.binaryInput, instance=4, name="FireAlarm.Status",
                     description="Fire alarm panel status", present_value=0),
        # --- Binary Output (commandable) ---
        BACnetObject(type=ObjectType.binaryOutput, instance=0, name="AHU1.SupplyFanCommand",
                     description="AHU-1 supply fan start/stop", relinquish_default=0),
        BACnetObject(type=ObjectType.binaryOutput, instance=1, name="Chiller1.EnableCommand",
                     description="Chiller-1 enable command", relinquish_default=0),
        BACnetObject(type=ObjectType.binaryOutput, instance=2, name="Pump1.StartCommand",
                     description="Pump-1 start command", relinquish_default=0),
        BACnetObject(type=ObjectType.binaryOutput, instance=3, name="Lighting.Zone1Command",
                     description="Lighting zone-1 on/off", relinquish_default=0),
        BACnetObject(type=ObjectType.binaryOutput, instance=4, name="Lighting.Zone2Command",
                     description="Lighting zone-2 on/off", relinquish_default=0),
        # --- Binary Value (commandable=true) ---
        BACnetObject(type=ObjectType.binaryValue, instance=0, name="System.OccupiedMode",
                     description="Building occupied/unoccupied", commandable=True,
                     relinquish_default=1),
        BACnetObject(type=ObjectType.binaryValue, instance=1, name="AHU1.Enable",
                     description="AHU-1 enable", commandable=True, relinquish_default=0),
        BACnetObject(type=ObjectType.binaryValue, instance=2, name="NightSetback.Active",
                     description="Night setback active", commandable=True, relinquish_default=0),
        BACnetObject(type=ObjectType.binaryValue, instance=3, name="Holiday.Mode",
                     description="Holiday mode", commandable=True, relinquish_default=0),
        BACnetObject(type=ObjectType.binaryValue, instance=4, name="Alarm.GlobalEnable",
                     description="Global alarm enable", commandable=True, relinquish_default=1),
        # --- Multi-State Input (read-only, PV starts at 1) ---
        BACnetObject(type=ObjectType.multiStateInput, instance=0, name="AHU1.UnitStatus",
                     description="AHU-1 unit status", present_value=3,
                     number_of_states=4, state_text=["Off", "Starting", "Running", "Fault"]),
        BACnetObject(type=ObjectType.multiStateInput, instance=1, name="Chiller1.Mode",
                     description="Chiller-1 mode", present_value=2,
                     number_of_states=3, state_text=["Off", "Cooling", "Standby"]),
        BACnetObject(type=ObjectType.multiStateInput, instance=2, name="System.Season",
                     description="System season", present_value=2,
                     number_of_states=3, state_text=["Heating", "Cooling", "Auto"]),
        BACnetObject(type=ObjectType.multiStateInput, instance=3, name="Zone1.FanSpeed",
                     description="Zone-1 fan speed", present_value=1,
                     number_of_states=3, state_text=["Low", "Medium", "High"]),
        BACnetObject(type=ObjectType.multiStateInput, instance=4, name="Generator.Status",
                     description="Generator status", present_value=1,
                     number_of_states=3, state_text=["Off", "Running", "Fault"]),
        # --- Multi-State Output (commandable) ---
        BACnetObject(type=ObjectType.multiStateOutput, instance=0, name="AHU1.FanSpeedCommand",
                     description="AHU-1 fan speed command", relinquish_default=1,
                     number_of_states=4, state_text=["Off", "Low", "Medium", "High"]),
        BACnetObject(type=ObjectType.multiStateOutput, instance=1, name="Damper.PositionCmd",
                     description="Damper position command", relinquish_default=1,
                     number_of_states=3, state_text=["Closed", "Minimum", "Open"]),
        BACnetObject(type=ObjectType.multiStateOutput, instance=2, name="Boiler.StageCommand",
                     description="Boiler stage command", relinquish_default=1,
                     number_of_states=3, state_text=["Off", "Stage1", "Stage2"]),
        BACnetObject(type=ObjectType.multiStateOutput, instance=3, name="Lighting.SceneCmd",
                     description="Lighting scene command", relinquish_default=1,
                     number_of_states=4, state_text=["Off", "On", "Dim", "Auto"]),
        BACnetObject(type=ObjectType.multiStateOutput, instance=4, name="Pump.SpeedCommand",
                     description="Pump speed command", relinquish_default=1,
                     number_of_states=3, state_text=["Off", "Low", "High"]),
        # --- Multi-State Value (commandable=true) ---
        BACnetObject(type=ObjectType.multiStateValue, instance=0, name="System.OperatingMode",
                     description="System operating mode", commandable=True, relinquish_default=1,
                     number_of_states=3, state_text=["Occupied", "Unoccupied", "Standby"]),
        BACnetObject(type=ObjectType.multiStateValue, instance=1, name="AHU1.FanMode",
                     description="AHU-1 fan mode", commandable=True, relinquish_default=1,
                     number_of_states=4, state_text=["Auto", "Low", "Medium", "High"]),
        BACnetObject(type=ObjectType.multiStateValue, instance=2, name="Zone1.HVACMode",
                     description="Zone-1 HVAC mode", commandable=True, relinquish_default=4,
                     number_of_states=4, state_text=["Off", "Heat", "Cool", "Auto"]),
        BACnetObject(type=ObjectType.multiStateValue, instance=3, name="Lighting.Scene",
                     description="Lighting scene", commandable=True, relinquish_default=1,
                     number_of_states=4, state_text=["Off", "Work", "Presentation", "Cleaning"]),
        BACnetObject(type=ObjectType.multiStateValue, instance=4, name="Chiller.Sequence",
                     description="Chiller sequence", commandable=True, relinquish_default=1,
                     number_of_states=3, state_text=["Lead", "Lag", "Standby"]),
        # --- CharacterString Value ---
        BACnetObject(type=ObjectType.characterstringValue, instance=0, name="Building.Name",
                     description="Building name", present_value="HQ Tower A"),
        BACnetObject(type=ObjectType.characterstringValue, instance=1, name="AHU1.Location",
                     description="AHU-1 location", present_value="Roof Level 12"),
        BACnetObject(type=ObjectType.characterstringValue, instance=2, name="System.FirmwareTag",
                     description="Firmware/version tag", present_value="BMS-SIM 1.0"),
        BACnetObject(type=ObjectType.characterstringValue, instance=3, name="Maintenance.Note",
                     description="Maintenance note", present_value="OK"),
        BACnetObject(type=ObjectType.characterstringValue, instance=4, name="Operator.Message",
                     description="Operator message banner", present_value="Normal operation"),
    ]

    return SimulatorConfig(
        connection=ConnectionConfig(
            bacnet_ip=BACnetIPConfig(),
            mstp=MSTPConfig(),
            network_number=0,
        ),
        device=DeviceConfig(),
        objects=objects,
    )


class ConfigStore:
    def __init__(self, path: Optional[Path] = None):
        self._path = path or CONFIG_FILE
        self._config: Optional[SimulatorConfig] = None
        self._save_handle: Optional[asyncio.TimerHandle] = None

    @property
    def config(self) -> SimulatorConfig:
        if self._config is None:
            self.load()
        return self._config  # type: ignore[return-value]

    def load(self) -> SimulatorConfig:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._config = SimulatorConfig.model_validate(raw)
        else:
            self._config = _default_seed()
            self._save_sync()
        return self._config

    def _save_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = self._config.model_dump(mode="json")  # type: ignore[union-attr]
        # atomic write: write to temp then rename
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def save_soon(self) -> None:
        """Debounced save — schedules a save after _SAVE_DELAY seconds."""
        loop = asyncio.get_event_loop()
        if self._save_handle is not None:
            self._save_handle.cancel()
        self._save_handle = loop.call_later(_SAVE_DELAY, self._save_sync)

    def save_now(self) -> None:
        if self._save_handle is not None:
            self._save_handle.cancel()
            self._save_handle = None
        self._save_sync()
