"""價格基準的更新規則（不碰 DB，原地修改 PriceBaseline）。"""

from app.modules.prices.models import PriceBaseline
from app.modules.prices.providers.base import Insights

# 沒有 Google 歷史資料打底時，要自己累積幾筆才判斷「歷史新低」
MIN_SAMPLES_FOR_RECORD = 3


def _lower(current: int | None, candidate: int) -> int:
    return candidate if current is None else min(current, candidate)


def apply_result(baseline: PriceBaseline, price: int, insights: Insights | None) -> None:
    if insights is not None:
        baseline.typical_low = insights.typical_low
        baseline.typical_high = insights.typical_high
        # 歷史最低只在第一次拿到時打底一次，之後只跟自己查到的價格比
        if not baseline.history_seeded and insights.history_low is not None:
            baseline.record_low = _lower(baseline.record_low, insights.history_low)
            baseline.history_seeded = True
    baseline.record_low = _lower(baseline.record_low, price)
    baseline.sample_count = (baseline.sample_count or 0) + 1


def history_ready(baseline: PriceBaseline | None) -> bool:
    if baseline is None:
        return False
    return baseline.history_seeded or baseline.sample_count >= MIN_SAMPLES_FOR_RECORD
