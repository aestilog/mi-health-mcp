"""睡眠分期映射（问题 1）与午睡识别（问题 3）的回归测试。

对应需求文档 ``docs/issues/2026-10-21-sleep-fix-spec.md`` 第二、三节。
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter

SHANGHAI = timezone(timedelta(hours=8))
DAY = "2026-10-20"


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


def _adapter() -> MiFitnessCloudAdapter:
    return MiFitnessCloudAdapter(user_id="u1", pass_token="p1")


async def _collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


async def _parse_sleep_records(monkeypatch, records):
    adapter = _adapter()
    # 按 cn 地区换算请求时间窗，区间才会覆盖整晚记录
    adapter.region = "cn"
    adapter._connected = True
    adapter._client = object()

    async def fake_fetch(key, start_date, end_date, region=None):
        assert key == "sleep"
        return records

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    return await _collect(adapter.iter_sleep_sessions(DAY, DAY))


def _sleep_item(payload: dict, sleep_start: datetime, zone_name: str = "Asia/Shanghai") -> dict:
    """构造一条云端睡眠记录；``sleep_start`` 是入睡时间，通过 ``bedtime`` 传入。"""
    return {
        "sid": "749078412_1",
        "time": _ts(sleep_start),
        "zone_offset": 28800,
        "zone_name": zone_name,
        "value": {"bedtime": _ts(sleep_start), **payload},
    }


def _segments(states_minutes: list[tuple[object, int]], start: datetime) -> list[dict]:
    items = []
    cursor = start
    for state, minutes in states_minutes:
        seg_end = cursor + timedelta(minutes=minutes)
        items.append({"state": state, "start_time": _ts(cursor), "end_time": _ts(seg_end)})
        cursor = seg_end
    return items


# ---------------------------------------------------------------------------
# 2.5 测试：睡眠分期映射
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (2, "deep"),
        (3, "light"),
        (4, "rem"),
        (5, "awake"),
    ],
)
def test_sleep_stage_name_known_states(state, expected):
    assert _adapter()._sleep_stage_name(state) == expected


def test_sleep_stage_name_state_6_is_unclassified_not_light():
    adapter = _adapter()
    assert adapter._sleep_stage_name(6) == "unclassified"
    assert adapter._sleep_stage_name(6) != "light"


@pytest.mark.parametrize("state", [1, 99, None, "abc", "", object(), [1], float("inf")])
def test_sleep_stage_name_unknown_states_are_unclassified(state):
    assert _adapter()._sleep_stage_name(state) == "unclassified"


@pytest.mark.parametrize("state", [1, 99, None, "abc"])
def test_sleep_stage_name_unknown_states_do_not_raise(state):
    try:
        _adapter()._sleep_stage_name(state)
    except Exception as exc:  # pragma: no cover - 只为给出清晰失败信息
        pytest.fail(f"unknown state {state!r} raised {exc!r}")


@pytest.mark.asyncio
async def test_sleep_session_record_with_only_state_6(monkeypatch):
    start = datetime(2026, 10, 20, 0, 30, tzinfo=SHANGHAI)
    record = _sleep_item(
        {"duration": 321, "items": _segments([(6, 321)], start)},
        start,
    )

    sessions = await _parse_sleep_records(monkeypatch, [record])

    assert len(sessions) == 1
    assert [stage.model_dump() for stage in sessions[0].stages] == [
        {"stage": "unclassified", "minutes": 321}
    ]


@pytest.mark.asyncio
async def test_sleep_session_stage_mapping_end_to_end(monkeypatch):
    start = datetime(2026, 10, 20, 0, 30, tzinfo=SHANGHAI)
    record = _sleep_item(
        {"duration": 200, "items": _segments([(2, 40), (3, 90), (4, 50), (5, 20)], start)},
        start,
    )

    sessions = await _parse_sleep_records(monkeypatch, [record])

    assert [(stage.stage, stage.minutes) for stage in sessions[0].stages] == [
        ("deep", 40),
        ("light", 90),
        ("rem", 50),
        ("awake", 20),
    ]


@pytest.mark.asyncio
async def test_duration_minutes_comes_from_payload_not_summed_items(monkeypatch):
    # 实测 2026-08-22：payload duration=407，items 相加 470（state 6 已含整晚 + state 5 重复）
    start = datetime(2026, 8, 21, 23, 0, tzinfo=SHANGHAI)
    record = _sleep_item(
        {"duration": 407, "items": _segments([(6, 407), (5, 63)], start)},
        start,
    )

    sessions = await _parse_sleep_records(monkeypatch, [record])

    session = sessions[0]
    assert session.duration_minutes == 407
    assert sum(stage.minutes for stage in session.stages) == 470
    # stages 之和大于 duration_minutes 属正常，不做修正
    assert sum(stage.minutes for stage in session.stages) > session.duration_minutes


# ---------------------------------------------------------------------------
# 3.5 测试：午睡识别
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("duration", "end_at", "expected"),
    [
        (25, datetime(2026, 10, 20, 13, 30, tzinfo=SHANGHAI), True),
        (25, datetime(2026, 10, 20, 3, 30, tzinfo=SHANGHAI), False),
        (120, datetime(2026, 10, 20, 13, 30, tzinfo=SHANGHAI), False),
        # 边界：11:00 整、16:59 尾、17:00 整（无秒，避免 duration 换算吃掉 199 秒）
        (59, datetime(2026, 10, 20, 11, 0, tzinfo=SHANGHAI), True),
        (59, datetime(2026, 10, 20, 16, 59, tzinfo=SHANGHAI), True),
        (59, datetime(2026, 10, 20, 17, 0, tzinfo=SHANGHAI), False),
    ],
)
@pytest.mark.asyncio
async def test_is_nap_detection(monkeypatch, duration, end_at, expected):
    item = {"zone_name": "Asia/Shanghai"}
    adapter = _adapter()
    assert adapter._is_nap_sleep(duration, end_at, item) is expected

    start = end_at - timedelta(minutes=duration)
    record = _sleep_item(
        {"duration": duration, "wake_up_time": _ts(end_at), "is_nap": None},
        start,
        zone_name="Asia/Shanghai",
    )
    sessions = await _parse_sleep_records(monkeypatch, [record])
    assert sessions[0].is_nap is expected


def test_is_nap_uses_zone_name_not_utc():
    """13:30 上海时间 = 05:30 UTC，若误用 UTC 会被判成夜间睡眠。"""
    end_at = datetime(2026, 10, 20, 13, 30, tzinfo=SHANGHAI)
    adapter = _adapter()
    assert end_at.astimezone(UTC).hour == 5
    assert adapter._is_nap_sleep(25, end_at, {"zone_name": "Asia/Shanghai"}) is True
