"""把觸發規則套到 DB：讀寫通知狀態、寫入 alert、站內通知與待寄紀錄。只 flush，由呼叫端 commit。"""

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert, AlertDelivery, WatchAlertState
from app.modules.alerts.rules import AlertState, BaselineView, Decision, evaluate
from app.modules.notifications.messages import alert_body, alert_title, watch_link
from app.modules.notifications.models import Notification
from app.modules.notifications.service import email_enabled
from app.modules.prices.models import PriceSnapshot
from app.modules.watches.models import PriceQuery, Watch


async def load_state(session: AsyncSession, watch_id: int) -> AlertState:
    row = await session.get(WatchAlertState, watch_id, populate_existing=True)
    if row is None:
        return AlertState()
    return AlertState(
        below_target=row.below_target,
        below_typical=row.below_typical,
        last_notified_price=row.last_notified_price,
    )


async def save_state(
    session: AsyncSession, watch_id: int, state: AlertState, notified_at: datetime | None
) -> None:
    values: dict[str, Any] = {
        "below_target": state.below_target,
        "below_typical": state.below_typical,
        "last_notified_price": state.last_notified_price,
    }
    if notified_at is not None:
        values["last_notified_at"] = notified_at
    stmt = insert(WatchAlertState).values(watch_id=watch_id, **values)
    await session.execute(
        stmt.on_conflict_do_update(index_elements=[WatchAlertState.watch_id], set_=values)
    )


async def reset_state(session: AsyncSession, watch_id: int) -> None:
    await session.execute(delete(WatchAlertState).where(WatchAlertState.watch_id == watch_id))


async def create_alert(
    session: AsyncSession,
    watch: Watch,
    snapshot_id: int,
    price: int,
    decision: Decision,
    *,
    created_at: datetime,
    deliver: bool,
) -> Alert | None:
    """同一筆快照已經對這個追蹤產生過 alert 時回傳 None，什麼都不寫。"""
    alert_id = await session.scalar(
        insert(Alert)
        .values(
            watch_id=watch.id,
            snapshot_id=snapshot_id,
            reason=decision.reasons[0],
            price=price,
            created_at=created_at,
        )
        .on_conflict_do_nothing(constraint="uq_alerts_watch_snapshot")
        .returning(Alert.id)
    )
    if alert_id is None:
        return None

    session.add(
        Notification(
            user_id=watch.user_id,
            type="price_alert",
            title=alert_title(watch.price_query, decision.reasons[0]),
            body=alert_body(price, watch.target_price, decision.reasons),
            link=watch_link(watch),
            alert_id=alert_id,
            created_at=created_at,
        )
    )
    if deliver:
        session.add(AlertDelivery(alert_id=alert_id, channel="email"))
    await session.flush()
    return await session.get(Alert, alert_id)


async def evaluate_watches(
    session: AsyncSession,
    query: PriceQuery,
    snapshot: PriceSnapshot,
    baseline: BaselineView,
    now: datetime,
) -> int:
    """對 query 底下 active 的追蹤套用規則，回傳產生的 alert 數。"""
    watches = await session.scalars(
        select(Watch)
        .where(Watch.price_query_id == query.id, Watch.status == "active")
        .order_by(Watch.id)
    )
    created = 0
    for watch in list(watches):
        decision = evaluate(
            await load_state(session, watch.id), snapshot.price, watch.target_price, baseline
        )
        if not decision.notify:
            await save_state(session, watch.id, decision.new_state, None)
            continue
        alert = await create_alert(
            session,
            watch,
            snapshot.id,
            snapshot.price,
            decision,
            created_at=now,
            deliver=await email_enabled(session, watch.user_id),
        )
        # 這筆快照已經處理過（例如重送），狀態也不要再動
        if alert is None:
            continue
        await save_state(session, watch.id, decision.new_state, now)
        created += 1
    return created
