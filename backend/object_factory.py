"""Map config BACnetObject → bacpypes3 object instances — docs/02, docs/04"""

from typing import Any, Dict

from bacpypes3.basetypes import PriorityValue
from bacpypes3.object import (
    AnalogInputObject,
    AnalogOutputObject,
    AnalogValueObject,
    BinaryInputObject,
    BinaryOutputObject,
    BinaryValueObject,
    CharacterStringValueObject,
    MultiStateInputObject,
    MultiStateOutputObject,
    MultiStateValueObject,
)

from .models import BACnetObject, ObjectType

_TYPE_MAP: Dict[ObjectType, tuple] = {
    ObjectType.analogInput:          (AnalogInputObject, "analog-input"),
    ObjectType.analogOutput:         (AnalogOutputObject, "analog-output"),
    ObjectType.analogValue:          (AnalogValueObject, "analog-value"),
    ObjectType.binaryInput:          (BinaryInputObject, "binary-input"),
    ObjectType.binaryOutput:         (BinaryOutputObject, "binary-output"),
    ObjectType.binaryValue:          (BinaryValueObject, "binary-value"),
    ObjectType.multiStateInput:      (MultiStateInputObject, "multi-state-input"),
    ObjectType.multiStateOutput:     (MultiStateOutputObject, "multi-state-output"),
    ObjectType.multiStateValue:      (MultiStateValueObject, "multi-state-value"),
    ObjectType.characterstringValue: (CharacterStringValueObject, "characterstring-value"),
}

_BINARY_TYPES = {ObjectType.binaryInput, ObjectType.binaryOutput, ObjectType.binaryValue}
_ANALOG_TYPES = {ObjectType.analogInput, ObjectType.analogOutput, ObjectType.analogValue}
_MULTISTATE_TYPES = {ObjectType.multiStateInput, ObjectType.multiStateOutput, ObjectType.multiStateValue}


def _make_priority_value(obj_type: ObjectType, value: Any) -> PriorityValue:
    """Wrap a raw value into a PriorityValue Choice — docs/04"""
    if value is None:
        return PriorityValue(null=())
    if obj_type in _BINARY_TYPES:
        return PriorityValue(enumerated=int(bool(value)))
    if obj_type in _MULTISTATE_TYPES:
        return PriorityValue(unsigned=int(value))
    if obj_type == ObjectType.characterstringValue:
        return PriorityValue(characterString=str(value))
    return PriorityValue(real=float(value))


def create_bacpypes_object(cfg: BACnetObject) -> Any:
    """Create a bacpypes3 object from a config BACnetObject."""
    entry = _TYPE_MAP.get(cfg.type)
    if entry is None:
        raise ValueError(f"unsupported object type: {cfg.type}")

    cls, type_str = entry

    kwargs: Dict[str, Any] = {
        "objectIdentifier": (type_str, cfg.instance),
        "objectName": cfg.name,
        "description": cfg.description,
        "outOfService": cfg.out_of_service,
        "statusFlags": [0, 0, 0, 0],
        "eventState": "normal",
    }

    # presentValue — docs/02 data types
    if cfg.type in _BINARY_TYPES:
        kwargs["presentValue"] = "active" if cfg.present_value else "inactive"
    elif cfg.type in _MULTISTATE_TYPES:
        kwargs["presentValue"] = int(cfg.present_value)
    else:
        kwargs["presentValue"] = cfg.present_value

    # units for analog types — docs/03 property 117
    if "units" in cls._elements:
        kwargs["units"] = cfg.units

    # multi-state: numberOfStates + stateText — docs/02
    if "numberOfStates" in cls._elements and cfg.number_of_states:
        kwargs["numberOfStates"] = cfg.number_of_states
    if "stateText" in cls._elements and cfg.state_text:
        kwargs["stateText"] = cfg.state_text

    # priority array + relinquish default for commandable objects — docs/04
    if "priorityArray" in cls._elements and cfg.commandable:
        kwargs["priorityArray"] = [
            _make_priority_value(cfg.type, slot) for slot in cfg.priority_array
        ]
        if "relinquishDefault" in cls._elements:
            if cfg.type in _BINARY_TYPES:
                kwargs["relinquishDefault"] = "active" if cfg.relinquish_default else "inactive"
            elif cfg.type in _MULTISTATE_TYPES:
                kwargs["relinquishDefault"] = int(cfg.relinquish_default)
            else:
                kwargs["relinquishDefault"] = cfg.relinquish_default

    obj = cls(**kwargs)
    obj._sim_commandable = cfg.commandable
    obj._sim_type = cfg.type
    return obj
