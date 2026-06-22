"""BACnet/IP integration test — ทดสอบ Who-Is, ReadProperty, WriteProperty กับ simulator"""

import asyncio
import sys

from bacpypes3.apdu import ErrorRejectAbortNack
from bacpypes3.app import Application
from bacpypes3.pdu import Address, IPv4Address


DEVICE_INSTANCE = 123456
DEVICE_NAME = "Building.Simulator"


async def test_all():
    results = []

    # Create a client application on a different port
    from bacpypes3.object import DeviceObject
    from bacpypes3.local.networkport import NetworkPortObject

    dev = DeviceObject(
        objectIdentifier=("device", 999999),
        objectName="Test.Client",
        vendorIdentifier=999,
        maxApduLengthAccepted=1476,
        segmentationSupported="segmented-both",
        apduTimeout=3000,
        numberOfApduRetries=3,
    )
    # Use a different port to avoid conflict with simulator
    npo = NetworkPortObject(
        "192.168.203.180/24:47809",
        objectIdentifier=("network-port", 1),
        objectName="TestNPO",
    )

    app = Application.from_object_list([dev, npo])

    # Give link layer time to bind
    await asyncio.sleep(2.0)

    sim_addr = IPv4Address("192.168.203.180:47808")

    # --- Test 1: Who-Is ---
    print("\n=== Test 1: Who-Is ===")
    try:
        i_ams = await asyncio.wait_for(
            app.who_is(DEVICE_INSTANCE, DEVICE_INSTANCE, sim_addr),
            timeout=5.0,
        )
        if i_ams:
            print(f"  PASS: Got I-Am from device {i_ams[0].iAmDeviceIdentifier}")
            results.append(("Who-Is", True))
        else:
            print("  FAIL: No I-Am response")
            results.append(("Who-Is", False))
    except asyncio.TimeoutError:
        print("  FAIL: Timeout")
        results.append(("Who-Is", False))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("Who-Is", False))

    # --- Test 2: ReadProperty — device object-name ---
    print("\n=== Test 2: ReadProperty device object-name ===")
    try:
        val = await asyncio.wait_for(
            app.read_property(sim_addr, f"device,{DEVICE_INSTANCE}", "objectName"),
            timeout=5.0,
        )
        print(f"  Got: {val}")
        if str(val) == DEVICE_NAME:
            print(f"  PASS")
            results.append(("ReadProperty device name", True))
        else:
            print(f"  FAIL: expected '{DEVICE_NAME}'")
            results.append(("ReadProperty device name", False))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("ReadProperty device name", False))

    # --- Test 3: ReadProperty — AI:0 presentValue ---
    print("\n=== Test 3: ReadProperty AI:0 presentValue ===")
    try:
        val = await asyncio.wait_for(
            app.read_property(sim_addr, "analog-input,0", "presentValue"),
            timeout=5.0,
        )
        print(f"  Got: {val} (type={type(val).__name__})")
        results.append(("ReadProperty AI:0 PV", True))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("ReadProperty AI:0 PV", False))

    # --- Test 4: ReadProperty — AV:1 presentValue ---
    print("\n=== Test 4: ReadProperty AV:1 presentValue ===")
    try:
        val = await asyncio.wait_for(
            app.read_property(sim_addr, "analog-value,1", "presentValue"),
            timeout=5.0,
        )
        print(f"  Got: {val}")
        results.append(("ReadProperty AV:1 PV", True))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("ReadProperty AV:1 PV", False))

    # --- Test 5: WriteProperty — AV:1 (not commandable, direct write) ---
    print("\n=== Test 5: WriteProperty AV:1 (non-commandable) ===")
    try:
        await asyncio.wait_for(
            app.write_property(sim_addr, "analog-value,1", "presentValue", 99.9),
            timeout=5.0,
        )
        # Read back
        val = await asyncio.wait_for(
            app.read_property(sim_addr, "analog-value,1", "presentValue"),
            timeout=5.0,
        )
        print(f"  Written 99.9, read back: {val}")
        if abs(float(val) - 99.9) < 0.01:
            print(f"  PASS")
            results.append(("WriteProperty AV:1", True))
        else:
            print(f"  FAIL: value mismatch")
            results.append(("WriteProperty AV:1", False))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("WriteProperty AV:1", False))

    # --- Test 6: WriteProperty — AI:0 (read-only, should be denied) ---
    print("\n=== Test 6: WriteProperty AI:0 (should be DENIED) ===")
    try:
        await asyncio.wait_for(
            app.write_property(sim_addr, "analog-input,0", "presentValue", 50.0),
            timeout=5.0,
        )
        print("  FAIL: write should have been denied")
        results.append(("WriteProperty AI:0 denied", False))
    except BaseException as e:
        err = str(e).lower()
        if "write-access-denied" in err or "writeaccessdenied" in err or "write" in err:
            print(f"  PASS: correctly denied")
            results.append(("WriteProperty AI:0 denied", True))
        else:
            print(f"  UNEXPECTED error: {e}")
            results.append(("WriteProperty AI:0 denied", False))

    # --- Test 7: WriteProperty — BV:0 commandable with priority ---
    print("\n=== Test 7: WriteProperty BV:0 commandable (priority 8) ===")
    try:
        from bacpypes3.primitivedata import Enumerated
        await asyncio.wait_for(
            app.write_property(
                sim_addr, "binary-value,0", "presentValue",
                Enumerated(1), priority=8,
            ),
            timeout=5.0,
        )
        val = await asyncio.wait_for(
            app.read_property(sim_addr, "binary-value,0", "presentValue"),
            timeout=5.0,
        )
        print(f"  Written active@P8, read back: {val}")
        results.append(("WriteProperty BV:0 commandable", True))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("WriteProperty BV:0 commandable", False))

    # --- Test 8: ReadPropertyMultiple — multiple objects ---
    print("\n=== Test 8: ReadPropertyMultiple ===")
    try:
        rpm_result = await asyncio.wait_for(
            app.read_property_multiple(
                sim_addr,
                [
                    "analog-input,0", ["objectName", "presentValue", "units"],
                    "binary-value,0", ["objectName", "presentValue"],
                ],
            ),
            timeout=5.0,
        )
        print(f"  Got {len(rpm_result)} property results")
        for item in rpm_result[:6]:
            print(f"    {item}")
        results.append(("ReadPropertyMultiple", True))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("ReadPropertyMultiple", False))

    # --- Test 9: ReadProperty — MSV:1 (multi-state) ---
    print("\n=== Test 9: ReadProperty MSV:1 ===")
    try:
        pv = await asyncio.wait_for(
            app.read_property(sim_addr, "multi-state-value,1", "presentValue"),
            timeout=5.0,
        )
        nos = await asyncio.wait_for(
            app.read_property(sim_addr, "multi-state-value,1", "numberOfStates"),
            timeout=5.0,
        )
        print(f"  PV={pv}, numberOfStates={nos}")
        results.append(("ReadProperty MSV:1", True))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("ReadProperty MSV:1", False))

    # --- Test 10: ReadProperty — CSV:0 (characterstring) ---
    print("\n=== Test 10: ReadProperty CSV:0 ===")
    try:
        val = await asyncio.wait_for(
            app.read_property(sim_addr, "characterstring-value,0", "presentValue"),
            timeout=5.0,
        )
        print(f"  Got: '{val}'")
        results.append(("ReadProperty CSV:0", True))
    except BaseException as e:
        print(f"  FAIL: {e}")
        results.append(("ReadProperty CSV:0", False))

    # --- Summary ---
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    print(f"\n  {passed}/{total} passed")

    app.close()
    return passed == total


if __name__ == "__main__":
    ok = asyncio.run(test_all())
    sys.exit(0 if ok else 1)
