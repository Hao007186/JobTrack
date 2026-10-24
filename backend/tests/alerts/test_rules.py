from app.modules.alerts.rules import AlertState, BaselineView, evaluate


def view(
    typical_low: int | None = None, record_low_before: int | None = None, ready: bool = False
) -> BaselineView:
    return BaselineView(
        typical_low=typical_low, record_low_before=record_low_before, history_ready_before=ready
    )


async def test_us06_scenario() -> None:
    state = AlertState()

    d = evaluate(state, 9500, 10000, view())
    assert d.notify
    assert d.reasons == ("below_target",)
    assert d.new_state.last_notified_price == 9500

    # 只比上次通知降 2%，即使是歷史新低也不通知
    d = evaluate(d.new_state, 9300, 10000, view(record_low_before=9500, ready=True))
    assert not d.notify
    assert d.reasons == ()

    d = evaluate(d.new_state, 8900, 10000, view(record_low_before=9300, ready=True))
    assert d.notify

    d = evaluate(d.new_state, 10500, 10000, view(record_low_before=8900, ready=True))
    assert not d.notify
    assert d.new_state.below_target is False
    assert d.new_state.last_notified_price == 8900

    # 回升後再跌破，視為新的一次
    d = evaluate(d.new_state, 9800, 10000, view(record_low_before=8900, ready=True))
    assert d.notify
    assert d.reasons == ("below_target",)


async def test_equal_to_target_triggers() -> None:
    assert evaluate(AlertState(), 10000, 10000, view()).notify


async def test_equal_to_typical_low_not_below() -> None:
    d = evaluate(AlertState(), 8000, 5000, view(typical_low=8000))
    assert not d.notify
    assert d.new_state.below_typical is False


async def test_record_low_first_time_notifies() -> None:
    d = evaluate(AlertState(), 8800, 5000, view(record_low_before=9000, ready=True))
    assert d.notify
    assert d.reasons == ("record_low",)


async def test_record_low_needs_history() -> None:
    assert not evaluate(AlertState(), 8800, 5000, view(record_low_before=9000)).notify


async def test_record_low_compares_before_value() -> None:
    assert not evaluate(AlertState(), 8800, 5000, view(record_low_before=8800, ready=True)).notify


async def test_typical_state_change() -> None:
    v = view(typical_low=8000)
    d = evaluate(AlertState(), 7900, 5000, v)
    assert d.notify
    assert d.reasons == ("below_typical",)

    d = evaluate(d.new_state, 7800, 5000, v)
    assert not d.notify

    d = evaluate(d.new_state, 8100, 5000, v)
    assert not d.notify
    assert d.new_state.below_typical is False

    d = evaluate(d.new_state, 7900, 5000, v)
    assert d.notify


async def test_merged_reasons_priority() -> None:
    d = evaluate(
        AlertState(), 8000, 10000, view(typical_low=9000, record_low_before=9500, ready=True)
    )
    assert d.reasons == ("below_target", "record_low", "below_typical")


async def test_five_percent_boundary() -> None:
    state = AlertState(below_target=True, last_notified_price=10000)
    assert evaluate(state, 9500, 20000, view()).notify
    assert not evaluate(state, 9501, 20000, view()).notify
