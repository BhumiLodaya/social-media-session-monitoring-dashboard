import csv
import io

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.tshark import TsharkUnavailable, _resolve_executable, capture_metadata


def test_tshark_executable_is_configurable_without_enabling_capture(monkeypatch):
    monkeypatch.setenv(
        "TSHARK_EXECUTABLE",
        r"C:\Users\bhumi\Downloads\Wireshark\tshark.exe",
    )
    settings = Settings(_env_file=None)

    assert settings.tshark_executable.endswith(r"Wireshark\tshark.exe")
    assert settings.network_capture_enabled is False


def test_missing_tshark_path_reports_a_clear_error(tmp_path):
    missing = tmp_path / "missing-tshark.exe"

    with pytest.raises(TsharkUnavailable, match="does not exist"):
        _resolve_executable(str(missing))


def test_unrunnable_tshark_path_reports_a_clear_error(tmp_path, monkeypatch):
    executable = tmp_path / "tshark.exe"
    executable.touch()

    def fail_to_run(*args, **kwargs):
        raise OSError("not runnable")

    monkeypatch.setattr("app.services.tshark.subprocess.run", fail_to_run)
    with pytest.raises(TsharkUnavailable, match="cannot run"):
        _resolve_executable(str(executable))


def test_capture_metadata_reads_tshark_protocol_field(monkeypatch):
    settings = Settings(
        _env_file=None,
        network_capture_enabled=True,
        network_capture_interface="test-interface",
        tshark_executable=r"C:\tshark.exe",
    )
    monkeypatch.setattr("app.services.tshark.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.tshark._resolve_executable", lambda _: r"C:\tshark.exe")

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return type("Result", (), {"stdout": b"", "stderr": b""})()
        return type(
            "Result",
            (),
            {
                "stdout": (
                    b'frame.time_epoch,_ws.col.protocol,ip.dst,frame.len\n'
                    b'"1791863468.681640600","TLSv1.2","10.35.155.131","558"\n'
                ),
                "stderr": b"",
            },
        )()

    monkeypatch.setattr("app.services.tshark.subprocess.run", fake_run)
    output = capture_metadata().decode()

    row = next(csv.DictReader(io.StringIO(output)))
    assert row["protocol"] == "TLSv1.2"
    assert row["destination"] == "10.35.155.131"


def test_capture_duration_is_validated():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, network_capture_duration_seconds=0)
