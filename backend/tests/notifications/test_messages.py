from datetime import date

from app.modules.notifications.messages import alert_body, alert_title, route_label
from app.modules.watches.models import PriceQuery


def _query(depart: date, ret: date | None) -> PriceQuery:
    return PriceQuery(origin="TPE", destination="NRT", depart_date=depart, return_date=ret)


async def test_route_label() -> None:
    assert route_label(_query(date(2026, 12, 19), date(2026, 12, 24))) == "TPE→NRT 12/19 來回"
    assert route_label(_query(date(2026, 12, 19), None)) == "TPE→NRT 12/19 單程"
    assert route_label(_query(date(2027, 1, 5), None)) == "TPE→NRT 1/5 單程"


async def test_alert_title_and_body() -> None:
    q = _query(date(2026, 12, 19), date(2026, 12, 24))
    assert alert_title(q, "below_target") == "TPE→NRT 12/19 來回：跌破目標價"
    assert alert_title(q, "record_low").endswith("：歷史新低")
    assert alert_title(q, "below_typical").endswith("：低於典型價格")

    assert (
        alert_body(9500, 10000, ("below_target", "record_low"))
        == "目前最低價 NT$9,500（目標價 NT$10,000）。同時是歷史新低。"
    )
    assert alert_body(9500, 10000, ("below_target", "record_low", "below_typical")) == (
        "目前最低價 NT$9,500（目標價 NT$10,000）。同時是歷史新低。同時低於典型價格。"
    )
    assert alert_body(7900, 5000, ("below_typical",)) == "目前最低價 NT$7,900（目標價 NT$5,000）。"
