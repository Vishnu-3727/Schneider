"""Minimal Modbus TCP server (stdlib only) for the SIMULATED meter and tests.

Implements what an energy meter needs: function 03 (read holding
registers) with the MBAP header, plus exception responses. 0x01 = illegal
function, 0x02 = illegal data address, 0x0B = gateway target (unit) failed
to respond. Written from the Modbus Application Protocol / Messaging on
TCP/IP specs, independently of pymodbus, so the pymodbus client is tested
against a separate implementation.
"""

from __future__ import annotations

import socket
import socketserver
import struct
import threading


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        srv: SimulatedModbusServer = self.server.owner  # type: ignore[attr-defined]
        sock = self.request
        srv._conns.add(sock)
        try:
            self._serve(srv, sock)
        except OSError:
            pass  # connection dropped (e.g. stop() simulating the device going offline)
        finally:
            srv._conns.discard(sock)

    def _serve(self, srv, sock) -> None:
        while True:
            head = _recv(sock, 7)
            if head is None:
                return
            tid, pid, length, unit = struct.unpack(">HHHB", head)
            pdu = _recv(sock, length - 1)
            if pdu is None:
                return
            if srv.delay_s:
                threading.Event().wait(srv.delay_s)
            sock.sendall(_frame(tid, pid, unit, srv.respond(unit, pdu)))


def _recv(sock, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _frame(tid: int, pid: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", tid, pid, len(pdu) + 1, unit) + pdu


class SimulatedModbusServer:
    def __init__(self, port: int, unit_id: int = 1, host: str = "127.0.0.1", size: int = 256) -> None:
        self.host, self.port, self.unit_id = host, port, unit_id
        self.registers = [0] * size
        self.delay_s = 0.0  # set > client timeout to emulate a timeout
        self._lock = threading.Lock()
        self._conns: set = set()
        self._srv: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def set(self, values: dict[int, int]) -> None:
        with self._lock:
            for addr, v in values.items():
                self.registers[addr] = v & 0xFFFF

    def respond(self, unit: int, pdu: bytes) -> bytes:
        fc = pdu[0]
        if unit != self.unit_id:
            return bytes([fc | 0x80, 0x0B])
        if fc != 0x03 or len(pdu) != 5:
            return bytes([fc | 0x80, 0x01])
        start, qty = struct.unpack(">HH", pdu[1:5])
        if not 1 <= qty <= 125 or start + qty > len(self.registers):
            return bytes([fc | 0x80, 0x02])
        with self._lock:
            regs = self.registers[start:start + qty]
        return bytes([0x03, 2 * qty]) + b"".join(struct.pack(">H", r) for r in regs)

    def start(self) -> None:
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._srv = socketserver.ThreadingTCPServer((self.host, self.port), _Handler)
        self._srv.daemon_threads = True
        self._srv.owner = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Go offline like a real device: stop listening AND drop open connections."""
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
        for s in list(self._conns):
            try:
                s.shutdown(socket.SHUT_RDWR)
                s.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(5)
