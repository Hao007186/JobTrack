from app.modules.prices.baseline import apply_result, history_ready
from app.modules.prices.models import PriceBaseline
from app.modules.prices.providers.base import Insights


def _baseline() -> PriceBaseline:
    return PriceBaseline(price_query_id=1, history_seeded=False, sample_count=0)


async def test_first_insights_seed_history() -> None:
    b = _baseline()
    apply_result(b, 9000, Insights(6400, 12500, 8000))
    assert (b.typical_low, b.typical_high) == (6400, 12500)
    assert b.record_low == 8000
    assert b.history_seeded is True
    assert b.sample_count == 1


async def test_record_low_takes_lower_price() -> None:
    b = _baseline()
    apply_result(b, 9000, Insights(6400, 12500, 8000))
    apply_result(b, 7500, None)
    assert b.record_low == 7500
    assert (b.typical_low, b.typical_high) == (6400, 12500)
    assert b.sample_count == 2


async def test_history_only_seeded_once() -> None:
    b = _baseline()
    apply_result(b, 9000, Insights(6400, 12500, 8000))
    apply_result(b, 8500, Insights(6000, 12000, 5000))
    assert b.record_low == 8000
    assert (b.typical_low, b.typical_high) == (6000, 12000)


async def test_insights_without_history_does_not_seed() -> None:
    b = _baseline()
    apply_result(b, 27524, Insights(15500, 26500, None))
    assert b.history_seeded is False
    assert b.record_low == 27524


async def test_no_insights_no_history() -> None:
    b = _baseline()
    for price in (9000, 8800, 9100):
        apply_result(b, price, None)
    assert b.typical_low is None
    assert b.history_seeded is False
    assert b.record_low == 8800


async def test_history_ready() -> None:
    assert history_ready(None) is False
    seeded = _baseline()
    apply_result(seeded, 9000, Insights(6400, 12500, 8000))
    assert history_ready(seeded) is True
    b = _baseline()
    apply_result(b, 9000, None)
    apply_result(b, 9000, None)
    assert history_ready(b) is False
    apply_result(b, 9000, None)
    assert history_ready(b) is True
