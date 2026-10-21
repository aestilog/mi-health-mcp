"""同一晚重复入库去重（问题 2）的回归测试。

对应需求文档 ``docs/issues/2026-10-21-sleep-fix-spec.md`` 第四节。
"""

from datetime import datetime, timedelta, timezone

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
    adapter.region = "cn"
    adapter._connected = True
    adapter._client = object()

    async def fake_fetch(key, start_date, end_date, region=None):
        assert key == "sleep"
        return records

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    return await _collect(adapter.iter_sleep_sessions(DAY, DAY))


def _segments(states_minutes: list[tuple[object, int]], start: datetime) -> list[dict]:
    items = []
    cursor = start
    for state, minutes in states_minutes:
        seg_end = cursor + timedelta(minutes=minutes)
        items.append({"state": state, "start_time": _ts(cursor), "end_time": _ts(seg_end)})
        cursor = seg_end
    return items


def _sleep_item(
    sid: str,
    start: datetime,
    duration: int | None = None,
    stages: list[tuple[object, int]] | None = None,
) -> dict:
    """构造一条云端睡眠记录；``duration`` 缺省时按有 items / 无 items 取默认值。"""
    if duration is None:
        duration = sum(minutes for _, minutes in stages) if stages else 120
    payload: dict = {
        "bedtime": _ts(start),
        "wake_up_time": _ts(start + timedelta(minutes=duration)),
        "duration": duration,
    }
    if stages is not None:
        payload["items"] = _segments(stages, start)
    return {
        "sid": sid,
        "time": _ts(start),
        "zone_offset": 28800,
        "zone_name": "Asia/Shanghai",
        "value": payload,
    }


def _platform(sid_suffix: str, start: datetime, duration=None, stages=None) -> dict:
    return _sleep_item(f"hlth.gen_{sid_suffix}", start, duration, stages)


def _device(sid_suffix: str, start: datetime, duration=None, stages=None) -> dict:
    return _sleep_item(f"749078412_{sid_suffix}", start, duration, stages)


# ---------------------------------------------------------------------------
# 4.6 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_have_rem_keep_record_with_more_rem_minutes(monkeypatch):
    start = datetime(2026, 10, 20, 0, 10, tzinfo=SHANGHAI)
    device = _device(
        "1", start, stages=[(2, 60), (3, 120), (4, 55), (5, 10), (6, 5)]
    )
    platform = _platform(
        "1", start + timedelta(minutes=20), stages=[(2, 50), (3, 180), (4, 40), (5, 10)]
    )

    sessions = await _parse_sleep_records(monkeypatch, [platform, device])

    assert len(sessions) == 1
    assert sessions[0].stages[2].stage == "rem"
    assert sessions[0].stages[2].minutes == 55


@pytest.mark.asyncio
async def test_record_with_rem_beats_record_without_rem(monkeypatch):
    start = datetime(2026, 10, 20, 0, 5, tzinfo=SHANGHAI)
    platform = _platform("1", start, stages=[(2, 90), (3, 300), (5, 20)])
    device = _device(
        "1", start + timedelta(minutes=15), stages=[(2, 40), (3, 100), (4, 30)]
    )

    sessions = await _parse_sleep_records(monkeypatch, [platform, device])

    assert len(sessions) == 1
    assert any(stage.stage == "rem" for stage in sessions[0].stages)
    assert sessions[0].duration_minutes == 170


@pytest.mark.asyncio
async def test_real_stages_beat_state_6_only(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    unclassified = _device("1", start, stages=[(6, 240)])
    platform = _platform("1", start + timedelta(minutes=10), stages=[(2, 60), (3, 170), (5, 10)])

    sessions = await _parse_sleep_records(monkeypatch, [unclassified, platform])

    assert len(sessions) == 1
    assert {stage.stage for stage in sessions[0].stages} == {"deep", "light", "awake"}


@pytest.mark.asyncio
async def test_two_records_without_items_keep_longer_duration(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    # 对应实测第 16 组：设备直传 161min 无分期 vs 健康平台 state 6 的 114min
    longer = _device("1", start, duration=161)
    shorter = _platform("1", start + timedelta(minutes=30), duration=114)

    sessions = await _parse_sleep_records(monkeypatch, [shorter, longer])

    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 161
    assert sessions[0].stages == []


@pytest.mark.asyncio
async def test_start_times_61_minutes_apart_are_not_merged(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    first = _platform("1", start, stages=[(2, 60), (3, 60)])
    second = _device("2", start + timedelta(minutes=61), duration=30)

    sessions = await _parse_sleep_records(monkeypatch, [first, second])

    assert len(sessions) == 2
    assert [session.start_at.strftime("%H:%M") for session in sessions] == ["00:00", "01:01"]


@pytest.mark.asyncio
async def test_identical_start_times_are_merged_into_one(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    platform = _platform("1", start, stages=[(2, 60), (3, 300), (5, 20)])
    device = _device("1", start, stages=[(2, 60), (3, 280), (4, 40)])

    sessions = await _parse_sleep_records(monkeypatch, [platform, device])

    assert len(sessions) == 1
    assert any(stage.stage == "rem" for stage in sessions[0].stages)


@pytest.mark.asyncio
async def test_single_record_is_returned_unchanged(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    record = _platform("1", start, stages=[(2, 60), (3, 300), (5, 20)])

    sessions = await _parse_sleep_records(monkeypatch, [record])

    assert len(sessions) == 1
    session = sessions[0]
    assert session.sleep_id == f"hlth.gen_1_{_ts(start)}"
    assert session.duration_minutes == 380
    assert [(stage.stage, stage.minutes) for stage in session.stages] == [
        ("deep", 60),
        ("light", 300),
        ("awake", 20),
    ]
    assert session.is_nap is False


# ---------------------------------------------------------------------------
# 4.3 / 4.5 补充：规则边界与不依赖返回顺序
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_6_only_and_no_items_compare_duration_only(monkeypatch):
    """4.6 第 8 条：state 6 与无 items 同属第 3 档，只比时长，161min 赢 114min。"""
    start = datetime(2026, 5, 24, 1, 1, tzinfo=SHANGHAI)
    # 实测：设备直传 01:01 161min 无 items vs 健康平台 01:46 114min 只有 state 6
    device = _device("1", start, duration=161)
    platform = _platform("1", start + timedelta(minutes=45), stages=[(6, 114)])

    sessions = await _parse_sleep_records(monkeypatch, [platform, device])

    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 161
    assert sessions[0].stages == []
    assert sessions[0].sleep_id == f"749078412_1_{_ts(start)}"


@pytest.mark.asyncio
async def test_state_6_longer_than_no_items_is_kept(monkeypatch):
    """4.6 第 9 条：同样是第 3 档，121min 的 state 6 赢 114min 的无 items。"""
    start = datetime(2026, 8, 1, 0, 0, tzinfo=SHANGHAI)
    # 对应实测第 19 组：健康平台 state 6 的 121min vs 设备直传 114min 无分期
    platform = _platform("1", start, stages=[(6, 121)])
    device = _device("1", start + timedelta(minutes=20), duration=114)

    sessions = await _parse_sleep_records(monkeypatch, [device, platform])

    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 121
    assert [(stage.stage, stage.minutes) for stage in sessions[0].stages] == [
        ("unclassified", 121)
    ]


@pytest.mark.asyncio
async def test_real_stages_keep_more_coverage(monkeypatch):
    """4.6 第 10 条：两条都有真实分期时，保留真实分期覆盖分钟数更多的那条。"""
    start = datetime(2026, 9, 27, 0, 0, tzinfo=SHANGHAI)
    # 覆盖更多的那条总时长反而略短，证明先比覆盖分钟数、再比 duration
    wide = _platform("1", start, duration=300, stages=[(2, 80), (3, 210), (5, 5)])
    narrow = _device("1", start + timedelta(minutes=15), duration=320, stages=[(2, 60), (3, 100)])

    sessions = await _parse_sleep_records(monkeypatch, [narrow, wide])

    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 300
    assert sum(stage.minutes for stage in sessions[0].stages) == 295


@pytest.mark.asyncio
async def test_start_time_does_not_outrank_longer_record_in_same_tier(monkeypatch):
    """同档内先比 duration，早睡的短记录不能压过晚睡的长记录。"""
    early = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    # 早睡的那条真实分期覆盖更少、时长也更短，仍硬塞一个更晚的 start 作干扰
    shorter = _device("1", early, duration=90, stages=[(2, 30), (3, 60)])
    longer = _platform("1", early + timedelta(minutes=30), duration=300, stages=[(2, 90), (3, 180)])

    sessions = await _parse_sleep_records(monkeypatch, [shorter, longer])

    assert len(sessions) == 1
    assert sessions[0].duration_minutes == 300


@pytest.mark.asyncio
async def test_dedupe_does_not_depend_on_record_order(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    platform = _platform("1", start, stages=[(2, 60), (3, 300), (5, 20)])
    device = _device("1", start + timedelta(minutes=5), stages=[(2, 60), (3, 250), (4, 70)])

    forward = await _parse_sleep_records(monkeypatch, [platform, device])
    backward = await _parse_sleep_records(monkeypatch, [device, platform])

    assert [session.sleep_id for session in forward] == [
        session.sleep_id for session in backward
    ]


@pytest.mark.asyncio
async def test_naps_are_kept_and_night_sleep_is_deduped_separately(monkeypatch):
    night = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    nap = datetime(2026, 10, 20, 13, 5, tzinfo=SHANGHAI)
    records = [
        _platform("night", night, stages=[(2, 60), (3, 300), (5, 20)]),
        _device("night", night + timedelta(minutes=10), stages=[(2, 60), (3, 280), (4, 40)]),
        _device("nap", nap, duration=25),
    ]

    sessions = await _parse_sleep_records(monkeypatch, records)

    assert len(sessions) == 2
    assert [session.is_nap for session in sessions] == [False, True]


@pytest.mark.asyncio
async def test_records_spanning_bucket_boundary_are_merged(monkeypatch):
    """08:59 与 09:00 分处整点两侧（对齐窗口的相邻两格），但只差 1 分钟，必须合并。"""
    first = datetime(2026, 10, 20, 8, 59, tzinfo=SHANGHAI)
    second = datetime(2026, 10, 20, 9, 0, tzinfo=SHANGHAI)
    records = [
        _platform("1", first, duration=100),
        _device("1", second, stages=[(2, 40), (3, 50)]),
    ]

    sessions = await _parse_sleep_records(monkeypatch, records)

    assert len(sessions) == 1
    assert {stage.stage for stage in sessions[0].stages} == {"deep", "light"}


@pytest.mark.asyncio
async def test_records_without_start_or_end_time_are_skipped(monkeypatch):
    start = datetime(2026, 10, 20, 0, 0, tzinfo=SHANGHAI)
    broken = _platform("broken", start, duration=300)
    broken["value"].pop("bedtime")
    good = _platform("good", start + timedelta(minutes=30), duration=300)

    sessions = await _parse_sleep_records(monkeypatch, [broken, good])

    assert len(sessions) == 1
    assert sessions[0].sleep_id == f"hlth.gen_good_{_ts(start + timedelta(minutes=30))}"
