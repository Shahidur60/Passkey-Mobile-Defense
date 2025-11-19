# ble_scanner.py — enforce ~0.5 m proximity (RSSI ≥ –58 dBm, needs 3 good samples)
import asyncio
from collections import defaultdict
from bleak import BleakScanner


class BleWatcher:
    """
    Scans for BLE advertisements and calls on_sid(sid)
    only when RSSI >= threshold for >= consecutive_hits times.
    """

    def __init__(self, on_sid, threshold=-58, consecutive_hits=3):
        self.on_sid = on_sid
        self.threshold = threshold
        self.consecutive_hits = consecutive_hits
        self._seen_good = defaultdict(int)
        self._seen_sid = set()

    async def _loop(self):
        def handle_adv(device, adv_data):
            try:
                rssi = getattr(adv_data, "rssi", None)
                if rssi is None:
                    rssi = getattr(device, "rssi", None)

                company_id = 0x1234
                payload = adv_data.manufacturer_data.get(company_id) if adv_data.manufacturer_data else None
                if not payload:
                    return

                sid = payload.decode("ascii", errors="ignore").strip()
                if not sid:
                    return

                # Log all advertisements for visibility
                print(f"[BLE] adv addr={getattr(device, 'address', '?')} RSSI={rssi} sid={sid}")

                if rssi is None:
                    return

                if rssi >= self.threshold:
                    self._seen_good[sid] += 1
                    print(f"[BLE] ✅ Strong signal {rssi} dBm for SID={sid} "
                          f"({self._seen_good[sid]}/{self.consecutive_hits})")
                    if self._seen_good[sid] >= self.consecutive_hits and sid not in self._seen_sid:
                        self._seen_sid.add(sid)
                        print(f"[BLE] 📶 Confirmed nearby (<0.5 m) SID={sid}")
                        self.on_sid(sid)
                        self._seen_good[sid] = 0
                else:
                    # reset counter if we lose strong signal
                    if sid in self._seen_good:
                        self._seen_good[sid] = 0
                    print(f"[BLE] ❌ Weak signal ({rssi} dBm) for SID={sid}")

            except Exception as e:
                print(f"[BLE] adv_data error: {e}")

        print(f"[BLE] 🔍 Scanner started — threshold={self.threshold} dBm (~0.5 m)")
        scanner = BleakScanner(handle_adv)

        try:
            await scanner.start()
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await scanner.stop()
            print("[BLE] 🛑 Scanner stopped")

    def run(self):
        try:
            asyncio.run(self._loop())
        except KeyboardInterrupt:
            print("[BLE] 🛑 Stopped manually")
