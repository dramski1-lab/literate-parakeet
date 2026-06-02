import http.client
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class TVDevice:
    name: str
    host: str
    port: int = 80
    health_endpoint: str = "/health"


@dataclass
class DeviceHealth:
    device: TVDevice
    status: HealthStatus
    reachable: bool
    http_status: Optional[int] = None
    error: Optional[str] = None


@dataclass
class HealthReport:
    devices: list = field(default_factory=list)

    @property
    def overall_status(self) -> HealthStatus:
        if not self.devices:
            return HealthStatus.UNKNOWN
        statuses = [d.status for d in self.devices]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        if any(s == HealthStatus.CRITICAL for s in statuses):
            return HealthStatus.CRITICAL
        return HealthStatus.DEGRADED

    @property
    def healthy_count(self) -> int:
        return sum(1 for d in self.devices if d.status == HealthStatus.HEALTHY)

    @property
    def total_count(self) -> int:
        return len(self.devices)


def check_device_connectivity(device: TVDevice, timeout: float = 5.0) -> tuple:
    try:
        with socket.create_connection((device.host, device.port), timeout=timeout):
            return True, None
    except socket.timeout:
        return False, "connection timed out"
    except ConnectionRefusedError:
        return False, "connection refused"
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    except OSError as e:
        return False, str(e)


def check_device_health(device: TVDevice, timeout: float = 5.0) -> DeviceHealth:
    reachable, error = check_device_connectivity(device, timeout)

    if not reachable:
        return DeviceHealth(
            device=device,
            status=HealthStatus.CRITICAL,
            reachable=False,
            error=error,
        )

    try:
        conn = http.client.HTTPConnection(device.host, device.port, timeout=timeout)
        conn.request("GET", device.health_endpoint)
        response = conn.getresponse()
        http_status = response.status
        conn.close()

        if 200 <= http_status < 300:
            status = HealthStatus.HEALTHY
        elif 400 <= http_status < 500:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.CRITICAL

        return DeviceHealth(
            device=device,
            status=status,
            reachable=True,
            http_status=http_status,
        )
    except Exception as e:
        return DeviceHealth(
            device=device,
            status=HealthStatus.DEGRADED,
            reachable=True,
            error=str(e),
        )


def run_health_check(devices: list, timeout: float = 5.0) -> HealthReport:
    report = HealthReport()
    for device in devices:
        report.devices.append(check_device_health(device, timeout))
    return report
