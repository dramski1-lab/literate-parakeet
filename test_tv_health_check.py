import http.client
import socket
from unittest.mock import MagicMock, patch

import pytest

from tv_health_check import (
    DeviceHealth,
    HealthReport,
    HealthStatus,
    TVDevice,
    check_device_connectivity,
    check_device_health,
    run_health_check,
)


# --- TVDevice ---

def test_tv_device_defaults():
    device = TVDevice(name="Living Room TV", host="192.168.1.100")
    assert device.port == 80
    assert device.health_endpoint == "/health"


def test_tv_device_custom_port_and_endpoint():
    device = TVDevice(name="Bedroom TV", host="tv.local", port=8080, health_endpoint="/api/health")
    assert device.port == 8080
    assert device.health_endpoint == "/api/health"


# --- HealthReport ---

def test_health_report_empty_is_unknown():
    assert HealthReport().overall_status == HealthStatus.UNKNOWN


def test_health_report_empty_counts():
    report = HealthReport()
    assert report.healthy_count == 0
    assert report.total_count == 0


def _make_device_health(status: HealthStatus, reachable: bool = True) -> DeviceHealth:
    device = TVDevice(name="TV", host="192.168.1.1")
    return DeviceHealth(device=device, status=status, reachable=reachable)


def test_health_report_all_healthy():
    report = HealthReport(devices=[
        _make_device_health(HealthStatus.HEALTHY),
        _make_device_health(HealthStatus.HEALTHY),
    ])
    assert report.overall_status == HealthStatus.HEALTHY
    assert report.healthy_count == 2
    assert report.total_count == 2


def test_health_report_one_critical_dominates():
    report = HealthReport(devices=[
        _make_device_health(HealthStatus.HEALTHY),
        _make_device_health(HealthStatus.CRITICAL, reachable=False),
    ])
    assert report.overall_status == HealthStatus.CRITICAL
    assert report.healthy_count == 1


def test_health_report_degraded_without_critical():
    report = HealthReport(devices=[
        _make_device_health(HealthStatus.HEALTHY),
        _make_device_health(HealthStatus.DEGRADED),
    ])
    assert report.overall_status == HealthStatus.DEGRADED


# --- check_device_connectivity ---

def test_connectivity_success():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("socket.create_connection", return_value=MagicMock()):
        reachable, error = check_device_connectivity(device)
    assert reachable is True
    assert error is None


def test_connectivity_timeout():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("socket.create_connection", side_effect=socket.timeout):
        reachable, error = check_device_connectivity(device)
    assert reachable is False
    assert "timed out" in error


def test_connectivity_refused():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        reachable, error = check_device_connectivity(device)
    assert reachable is False
    assert "refused" in error


def test_connectivity_dns_failure():
    device = TVDevice(name="TV1", host="nonexistent.local")
    with patch("socket.create_connection", side_effect=socket.gaierror("Name not found")):
        reachable, error = check_device_connectivity(device)
    assert reachable is False
    assert "DNS" in error


def test_connectivity_os_error():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("socket.create_connection", side_effect=OSError("network unreachable")):
        reachable, error = check_device_connectivity(device)
    assert reachable is False
    assert "network unreachable" in error


# --- check_device_health ---

def _mock_http_response(status_code: int):
    mock_response = MagicMock()
    mock_response.status = status_code
    mock_conn = MagicMock()
    mock_conn.getresponse.return_value = mock_response
    return mock_conn


def test_device_health_unreachable_is_critical():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("tv_health_check.check_device_connectivity", return_value=(False, "connection timed out")):
        health = check_device_health(device)
    assert health.status == HealthStatus.CRITICAL
    assert health.reachable is False
    assert health.error == "connection timed out"
    assert health.http_status is None


def test_device_health_200_is_healthy():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("tv_health_check.check_device_connectivity", return_value=(True, None)):
        with patch("http.client.HTTPConnection", return_value=_mock_http_response(200)):
            health = check_device_health(device)
    assert health.status == HealthStatus.HEALTHY
    assert health.reachable is True
    assert health.http_status == 200


def test_device_health_204_is_healthy():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("tv_health_check.check_device_connectivity", return_value=(True, None)):
        with patch("http.client.HTTPConnection", return_value=_mock_http_response(204)):
            health = check_device_health(device)
    assert health.status == HealthStatus.HEALTHY
    assert health.http_status == 204


def test_device_health_404_is_degraded():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("tv_health_check.check_device_connectivity", return_value=(True, None)):
        with patch("http.client.HTTPConnection", return_value=_mock_http_response(404)):
            health = check_device_health(device)
    assert health.status == HealthStatus.DEGRADED
    assert health.http_status == 404


def test_device_health_503_is_critical():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("tv_health_check.check_device_connectivity", return_value=(True, None)):
        with patch("http.client.HTTPConnection", return_value=_mock_http_response(503)):
            health = check_device_health(device)
    assert health.status == HealthStatus.CRITICAL
    assert health.http_status == 503


def test_device_health_http_exception_is_degraded():
    device = TVDevice(name="TV1", host="192.168.1.1")
    with patch("tv_health_check.check_device_connectivity", return_value=(True, None)):
        with patch("http.client.HTTPConnection", side_effect=Exception("connection reset")):
            health = check_device_health(device)
    assert health.status == HealthStatus.DEGRADED
    assert health.reachable is True
    assert "connection reset" in health.error


# --- run_health_check ---

def test_run_health_check_empty_devices():
    report = run_health_check([])
    assert report.total_count == 0
    assert report.overall_status == HealthStatus.UNKNOWN


def test_run_health_check_all_healthy():
    devices = [
        TVDevice(name="TV1", host="192.168.1.1"),
        TVDevice(name="TV2", host="192.168.1.2"),
    ]
    with patch("tv_health_check.check_device_connectivity", return_value=(True, None)):
        with patch("http.client.HTTPConnection", return_value=_mock_http_response(200)):
            report = run_health_check(devices)
    assert report.total_count == 2
    assert report.healthy_count == 2
    assert report.overall_status == HealthStatus.HEALTHY


def test_run_health_check_mixed_status():
    devices = [
        TVDevice(name="TV1", host="192.168.1.1"),
        TVDevice(name="TV2", host="192.168.1.2"),
    ]

    def fake_connectivity(device, timeout=5.0):
        return device.host == "192.168.1.1", None if device.host == "192.168.1.1" else "timed out"

    with patch("tv_health_check.check_device_connectivity", side_effect=fake_connectivity):
        with patch("http.client.HTTPConnection", return_value=_mock_http_response(200)):
            report = run_health_check(devices)

    assert report.total_count == 2
    assert report.overall_status == HealthStatus.CRITICAL


def test_run_health_check_preserves_device_order():
    devices = [TVDevice(name=f"TV{i}", host=f"192.168.1.{i}") for i in range(1, 4)]
    with patch("tv_health_check.check_device_connectivity", return_value=(True, None)):
        with patch("http.client.HTTPConnection", return_value=_mock_http_response(200)):
            report = run_health_check(devices)
    assert [d.device.name for d in report.devices] == ["TV1", "TV2", "TV3"]
