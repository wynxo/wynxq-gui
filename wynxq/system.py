"""Measured runtime state for the System panel.

Every number here is read from something real: `/proc` for memory, Ollama's own
`/api/ps` for what is resident and where. Nothing is estimated, and a value that
cannot be measured on this machine is omitted rather than filled in — a status
surface that invents a figure is worse than one that admits it does not know.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    values[key] = int(parts[0]) * 1024        # kB -> bytes
    except OSError:
        return {}
    return values


def process_memory() -> int:
    """Resident set size of this process, in bytes. 0 when unavailable."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        return int(parts[1]) * 1024
    except OSError:
        pass
    return 0


def system_memory() -> dict:
    info = _read_meminfo()
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    if not total:
        return {}
    return {"total": total, "available": available, "used": max(0, total - available)}


def gpu_memory() -> dict:
    """Total and used VRAM, only when a vendor tool can be asked directly."""
    if not shutil.which("nvidia-smi"):
        return {}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    line = result.stdout.strip().splitlines()
    if not line:
        return {}
    parts = [part.strip() for part in line[0].split(",")]
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        return {}
    return {"total": int(parts[0]) * 1024 * 1024, "used": int(parts[1]) * 1024 * 1024}


def disk_free(path) -> dict:
    try:
        usage = shutil.disk_usage(str(path or Path.home()))
    except (OSError, ValueError):
        return {}
    return {"total": usage.total, "free": usage.free, "used": usage.used}


def human_bytes(count) -> str:
    try:
        size = float(count)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if size >= 100 or unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def resident_models(entries) -> list[dict]:
    """Ollama's own view of what is loaded, and whether it is on the GPU."""
    resident = []
    for entry in entries or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        total = int(entry.get("size", 0) or 0)
        vram = int(entry.get("size_vram", 0) or 0)
        if total > 0 and vram >= total:
            placement = "GPU"
        elif vram > 0:
            placement = "GPU + CPU"
        elif total > 0:
            placement = "CPU"
        else:
            placement = ""
        resident.append({
            "name": str(entry["name"]),
            "size": total,
            "sizeLabel": human_bytes(total),
            "vram": vram,
            "vramLabel": human_bytes(vram),
            "placement": placement,
            "expires": str(entry.get("expires_at", "") or ""),
        })
    return resident
