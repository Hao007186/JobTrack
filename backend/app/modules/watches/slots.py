"""名額規則：全站鎖、query_hash、佔名額判斷、決定狀態與補位。"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date

MAX_ACTIVE_QUERIES = 8
MAX_WATCHES_PER_USER = 3
# 出發前 2 天停止查價
STOP_CHECK_DAYS = 2
# pg_advisory_xact_lock 的鍵，"FARE" 的 ASCII
WATCH_LOCK_KEY = 0x46415245


@dataclass(frozen=True)
class QueryConditions:
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: str
    adults: int
    airlines: tuple[str, ...]
    is_demo: bool

    def query_hash(self) -> str:
        payload = {
            "origin": self.origin,
            "destination": self.destination,
            "depart_date": self.depart_date.isoformat(),
            "return_date": self.return_date.isoformat() if self.return_date else None,
            "cabin": self.cabin,
            "adults": self.adults,
            "airlines": sorted(self.airlines),
            "is_demo": self.is_demo,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
