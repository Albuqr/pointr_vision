"""The PC's power state for run.json `power` (contract 0.16.0, D-053).

Windows only, through GetSystemPowerStatus with ctypes (no dependency). Anything the OS does not
say is None, never a guess."""

import ctypes
import sys
from ctypes import wintypes


class SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def system_power_status() -> SystemPowerStatus | None:
    """The OS answer, or None when this OS has no reader or the call fails."""
    if sys.platform != "win32":
        return None
    status = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    return status


def read_power() -> dict:
    """{ac, battery_percent}: ac is True on mains, False on battery; each None when unknown."""
    try:
        status = system_power_status()
    except Exception:  # a failing probe must not stop a run; the field says "not known"
        status = None
    if status is None:
        return {"ac": None, "battery_percent": None}
    ac = {0: False, 1: True}.get(status.ACLineStatus)
    percent = status.BatteryLifePercent  # 255 is "unknown"; only 0 to 100 is a charge
    return {"ac": ac, "battery_percent": percent if percent <= 100 else None}
