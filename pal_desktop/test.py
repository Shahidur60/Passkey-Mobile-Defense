from bleak import BleakScanner
import asyncio

async def test():
    devices = await BleakScanner.discover(timeout=5)
    for d in devices:
        md = getattr(d, "metadata", {})
        if not md or "manufacturer_data" not in md:
            continue
        print(f"Device: {d.name}")
        for mid, v in md["manufacturer_data"].items():
            print(f"  ID {mid}: {v}")

asyncio.run(test())
