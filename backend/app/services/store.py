"""Bounded, process-local demo storage. Restarting the API clears scans."""

from collections import OrderedDict
from threading import Lock
from uuid import UUID

from app.schemas import ScanResponse


class ScanStore:
    def __init__(self, capacity: int = 100):
        self.capacity = max(1, capacity)
        self._scans: OrderedDict[UUID, ScanResponse] = OrderedDict()
        self._lock = Lock()

    def save(self, scan: ScanResponse) -> None:
        with self._lock:
            self._scans[scan.id] = scan
            while len(self._scans) > self.capacity:
                self._scans.popitem(last=False)

    def get(self, scan_id: UUID) -> ScanResponse | None:
        with self._lock:
            return self._scans.get(scan_id)
