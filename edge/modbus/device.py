"""Modbus devices: one small read interface, a mock and a real TCP client.

Both raise the same two errors so the poller treats them identically:
  DeviceTimeout      - the device did not answer in time
  DeviceUnavailable  - no connection / the device refused or returned an error
MockModbusDevice is explicitly a mock (tests, demos without hardware).
PymodbusTcpDevice talks Modbus TCP (a meter, or an RTU meter behind a
TCP gateway) via pymodbus. It is imported lazily so the edge package still
loads without the optional [edge] extra.
"""

from __future__ import annotations


class DeviceTimeout(Exception):
    pass


class DeviceUnavailable(Exception):
    pass


class MockModbusDevice:
    """In-memory holding registers. fail = None | "timeout" | "unavailable"."""

    def __init__(self, registers: dict[int, int] | None = None) -> None:
        self.registers = dict(registers or {})
        self.fail: str | None = None
        self.reads = 0

    def read(self, address: int, count: int) -> list[int]:
        self.reads += 1
        if self.fail == "timeout":
            raise DeviceTimeout("mock device timed out")
        if self.fail == "unavailable":
            raise DeviceUnavailable("mock device unreachable")
        return [self.registers.get(address + k, 0) for k in range(count)]

    def close(self) -> None:
        pass


class PymodbusTcpDevice:
    def __init__(self, host: str, port: int = 502, device_id: int = 1, timeout_s: float = 2.0) -> None:
        from pymodbus.client import ModbusTcpClient

        self.device_id = device_id
        self._client = ModbusTcpClient(host, port=port, timeout=timeout_s, retries=0)

    def read(self, address: int, count: int) -> list[int]:
        from pymodbus.exceptions import ConnectionException, ModbusIOException

        try:
            if not self._client.connected and not self._client.connect():
                raise DeviceUnavailable("cannot connect to Modbus device")
            rr = self._client.read_holding_registers(address, count=count, device_id=self.device_id)
        except ModbusIOException as exc:
            self._client.close()
            raise DeviceTimeout(str(exc)) from exc
        except (ConnectionException, OSError) as exc:
            self._client.close()
            raise DeviceUnavailable(str(exc)) from exc
        if rr.isError():
            raise DeviceUnavailable(f"Modbus exception response: {rr}")
        return list(rr.registers)

    def close(self) -> None:
        self._client.close()
