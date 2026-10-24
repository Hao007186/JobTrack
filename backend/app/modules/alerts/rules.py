"""觸發規則（不碰 DB）：狀態變化才通知，沒有變化時要比上次通知再降 5%。"""

from dataclasses import dataclass

from app.modules.alerts.models import ALERT_REASONS

# 沒有狀態變化時，價格要 <= 上次通知價格的 95% 才再通知
RENOTIFY_PERCENT = 95


@dataclass(frozen=True)
class AlertState:
    below_target: bool = False
    below_typical: bool = False
    last_notified_price: int | None = None


@dataclass(frozen=True)
class BaselineView:
    # 這次更新後的典型區間下緣
    typical_low: int | None
    # 這筆價格併入之前的歷史最低；跟併入後的值比永遠不會成立
    record_low_before: int | None
    history_ready_before: bool


@dataclass(frozen=True)
class Decision:
    notify: bool
    # 依優先順序排列；notify 為 False 時為空
    reasons: tuple[str, ...]
    new_state: AlertState


def evaluate(state: AlertState, price: int, target_price: int, baseline: BaselineView) -> Decision:
    met = {
        "below_target": price <= target_price,
        "record_low": (
            baseline.history_ready_before
            and baseline.record_low_before is not None
            and price < baseline.record_low_before
        ),
        "below_typical": baseline.typical_low is not None and price < baseline.typical_low,
    }
    newly = (met["below_target"] and not state.below_target) or (
        met["below_typical"] and not state.below_typical
    )

    if newly:
        notify = True
    elif any(met.values()):
        last = state.last_notified_price
        # 整數運算，避免浮點誤差
        notify = last is None or price * 100 <= last * RENOTIFY_PERCENT
    else:
        notify = False

    reasons = tuple(r for r in ALERT_REASONS if met[r]) if notify else ()
    new_state = AlertState(
        below_target=met["below_target"],
        below_typical=met["below_typical"],
        last_notified_price=price if notify else state.last_notified_price,
    )
    return Decision(notify=notify, reasons=reasons, new_state=new_state)
