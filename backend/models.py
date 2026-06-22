"""Pydantic models for BACnet simulator config/objects/connection — docs/08"""

from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# --- Object types (docs/02) ---

class ObjectType(str, Enum):
    analogInput = "analogInput"
    analogOutput = "analogOutput"
    analogValue = "analogValue"
    binaryInput = "binaryInput"
    binaryOutput = "binaryOutput"
    binaryValue = "binaryValue"
    multiStateInput = "multiStateInput"
    multiStateOutput = "multiStateOutput"
    multiStateValue = "multiStateValue"
    characterstringValue = "characterstringValue"


READONLY_TYPES = {ObjectType.analogInput, ObjectType.binaryInput, ObjectType.multiStateInput}
ALWAYS_COMMANDABLE_TYPES = {ObjectType.analogOutput, ObjectType.binaryOutput, ObjectType.multiStateOutput}
OPTIONALLY_COMMANDABLE_TYPES = {ObjectType.analogValue, ObjectType.binaryValue, ObjectType.multiStateValue}
MULTISTATE_TYPES = {
    ObjectType.multiStateInput, ObjectType.multiStateOutput, ObjectType.multiStateValue,
}


# --- Connection settings (docs/05, docs/06) ---

class BACnetIPConfig(BaseModel):
    enabled: bool = True
    interface: str = "auto"
    port: int = Field(default=47808, ge=1, le=65535)
    apdu_timeout_ms: int = Field(default=3000, ge=500, le=30000)
    apdu_retries: int = Field(default=3, ge=0, le=10)
    segmentation: str = Field(default="both")
    max_apdu_length: int = Field(default=1476, ge=50, le=1476)


class MSTPConfig(BaseModel):
    enabled: bool = False
    serial_port: str = ""
    baud: int = Field(default=38400)
    mac_address: int = Field(default=1, ge=0, le=127)
    max_master: int = Field(default=127, ge=0, le=127)
    max_info_frames: int = Field(default=1, ge=1, le=255)

    @field_validator("baud")
    @classmethod
    def validate_baud(cls, v: int) -> int:
        allowed = (9600, 19200, 38400, 57600, 76800, 115200)
        if v not in allowed:
            raise ValueError(f"baud must be one of {allowed}")
        return v


class ConnectionConfig(BaseModel):
    bacnet_ip: BACnetIPConfig = Field(default_factory=BACnetIPConfig)
    mstp: MSTPConfig = Field(default_factory=MSTPConfig)
    network_number: int = Field(default=0, ge=0, le=65534)


# --- Device settings (docs/08) ---

class DeviceConfig(BaseModel):
    instance: int = Field(default=123456, ge=0, le=4194302)
    name: str = "Building.Simulator"
    vendor_id: int = Field(default=0, ge=0)
    vendor_name: str = "BMS Simulator"


# --- BACnet object definition (docs/02, docs/03, docs/04, docs/08) ---

class BACnetObject(BaseModel):
    type: ObjectType
    instance: int = Field(ge=0)
    name: str
    description: str = ""
    present_value: Union[float, int, str] = 0
    units: int = Field(default=95)  # 95 = no-units
    commandable: bool = False
    relinquish_default: Union[float, int, str] = 0
    priority_array: List[Optional[Union[float, int, str]]] = Field(
        default_factory=lambda: [None] * 16,
    )
    number_of_states: Optional[int] = None
    state_text: Optional[List[str]] = None
    out_of_service: bool = False
    random_enabled: bool = False
    random_min: Optional[float] = None
    random_max: Optional[float] = None
    random_interval: float = Field(default=5.0, ge=0.5, le=300.0)

    @field_validator("priority_array")
    @classmethod
    def pad_priority_array(cls, v: list) -> list:
        if len(v) < 16:
            v.extend([None] * (16 - len(v)))
        return v[:16]

    @model_validator(mode="after")
    def enforce_commandable(self) -> "BACnetObject":
        # docs/04: AO/BO/MO always commandable, AI/BI/MSI never
        if self.type in ALWAYS_COMMANDABLE_TYPES:
            self.commandable = True
        elif self.type in READONLY_TYPES:
            self.commandable = False
        return self


# --- Top-level config (docs/08 โครง devices.json) ---

class SimulatorConfig(BaseModel):
    connection: ConnectionConfig = Field(default_factory=ConnectionConfig)
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    objects: List[BACnetObject] = Field(default_factory=list)
