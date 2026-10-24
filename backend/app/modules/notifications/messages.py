"""通知的標題與內文；站內通知和 Email 共用同一份文字。"""

from app.modules.watches.models import PriceQuery, Watch

_REASON_TITLES = {
    "below_target": "跌破目標價",
    "record_low": "歷史新低",
    "below_typical": "低於典型價格",
}
# 主要原因以外的原因接在內文後面；below_target 一定是主要原因，不會出現在這裡
_EXTRA_REASONS = {
    "record_low": "同時是歷史新低。",
    "below_typical": "同時低於典型價格。",
}

ACTIVATED_BODY = "排隊中的追蹤已啟用，接下來每天查價。"
QUOTA_TITLE = "本月查價額度已用完"
QUOTA_BODY = "本月的查價額度已用完，所有追蹤暫停查價，下個月 1 號恢復。"


def route_label(query: PriceQuery) -> str:
    d = query.depart_date
    trip = "單程" if query.return_date is None else "來回"
    return f"{query.origin}→{query.destination} {d.month}/{d.day} {trip}"


def alert_title(query: PriceQuery, reason: str) -> str:
    return f"{route_label(query)}：{_REASON_TITLES[reason]}"


def alert_body(price: int, target_price: int, reasons: tuple[str, ...]) -> str:
    extras = "".join(_EXTRA_REASONS[r] for r in reasons[1:])
    return f"目前最低價 NT${price:,}（目標價 NT${target_price:,}）。{extras}"


def watch_link(watch: Watch) -> str:
    return f"/watches/{watch.public_id}"


def activated_title(query: PriceQuery) -> str:
    return f"{route_label(query)} 已開始查價"
