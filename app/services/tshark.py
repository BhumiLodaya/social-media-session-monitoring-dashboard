import csv
import io
import shutil
import subprocess
from pathlib import Path

from app.config import get_settings


class TsharkUnavailable(RuntimeError):
    pass


def _resolve_executable(configured_path: str | None) -> str:
    if configured_path and configured_path.strip():
        path = Path(configured_path.strip())
        if not path.is_file():
            raise TsharkUnavailable(f"TSHARK_EXECUTABLE does not exist: {path}")
        executable = str(path)
    else:
        executable = shutil.which("tshark") or ""
        if not executable:
            raise TsharkUnavailable(
                "tshark executable was not found; set TSHARK_EXECUTABLE to its full path"
            )

    try:
        subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        source = "TSHARK_EXECUTABLE" if configured_path else "tshark"
        raise TsharkUnavailable(f"{source} cannot run: {executable}") from exc
    return executable


def capture_metadata() -> bytes:
    settings = get_settings()
    if not settings.network_capture_enabled:
        raise TsharkUnavailable("live capture is disabled; set NETWORK_CAPTURE_ENABLED=true only for an authorized interface")
    if not settings.network_capture_interface:
        raise TsharkUnavailable("NETWORK_CAPTURE_INTERFACE is not configured")
    executable = _resolve_executable(settings.tshark_executable)
    command = [
        executable, "-i", settings.network_capture_interface,
        "-a", f"duration:{settings.network_capture_duration_seconds}",
        "-T", "fields", "-E", "header=y", "-E", "separator=,", "-E", "quote=d",
        "-e", "frame.time_epoch", "-e", "_ws.col.protocol",
        "-e", "ip.dst", "-e", "frame.len",
    ]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, timeout=settings.network_capture_duration_seconds + 10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TsharkUnavailable("authorized tshark capture failed") from exc
    rows = csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["timestamp", "protocol", "destination", "bytes"])
    writer.writeheader()
    from datetime import datetime, UTC
    for row in rows:
        try:
            timestamp = datetime.fromtimestamp(float(row["frame.time_epoch"]), UTC).isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        writer.writerow({
            "timestamp": timestamp,
            "protocol": row.get("_ws.col.protocol") or row.get("_ws.col.Protocol") or "other",
            "destination": row.get("ip.dst", ""),
            "bytes": row.get("frame.len", ""),
        })
    return output.getvalue().encode()
