import pytest

from mi_fitness_mcp.adapters.mi_fitness_cloud import (
    MiFitnessCloudAdapter,
    _is_authentication_error,
)


async def _collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


def test_optional_number_helpers():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._optional_float(0) is None
    assert adapter._optional_float("1.5") == 1.5
    assert adapter._optional_int(0) is None
    assert adapter._optional_int("7") == 7


def test_parse_value_dict_and_json():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._parse_value({"value": {"steps": 1}}) == {"steps": 1}
    assert adapter._parse_value({"value": '{"steps": 2}'}) == {"steps": 2}


def test_record_datetime_uses_zone_offset():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    dt = adapter._record_datetime({"time": 0, "zone_offset": 10800})
    assert dt.isoformat().startswith("1970-01-01T03:00:00")


@pytest.mark.asyncio
async def test_iter_daily_activity_aggregates_steps_and_calories(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    adapter._connected = True
    adapter._client = object()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "steps":
            return [
                {
                    "time": 1743467400,
                    "zone_offset": 0,
                    "value": '{"steps": 10, "distance": 8, "calories": 1}',
                },
                {
                    "time": 1743467460,
                    "zone_offset": 0,
                    "value": '{"steps": 20, "distance": 16, "calories": 2}',
                },
            ]
        if key == "calories":
            return [
                {"time": 1743467400, "zone_offset": 0, "value": '{"calories": 5}'},
                {"time": 1743467460, "zone_offset": 0, "value": '{"calories": 7}'},
            ]
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    items = await _collect(adapter.iter_daily_activity("2025-04-01", "2025-04-01"))

    assert len(items) == 1
    assert items[0].steps == 30
    assert items[0].distance_m == 24
    assert items[0].active_kcal == 12


def test_dedupe_by_timestamp_keeps_max_record_per_minute():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    items = [
        {"time": 100, "value": '{"steps": 50, "distance": 40, "calories": 3}'},
        {"time": 100, "value": '{"steps": 47, "distance": 37, "calories": 3}'},
        {"time": 160, "value": '{"steps": 10, "distance": 8, "calories": 1}'},
    ]

    deduped = adapter._dedupe_by_timestamp(items, "steps")

    assert [int(item["time"]) for item in deduped] == [100, 160]
    assert adapter._parse_value(deduped[0])["steps"] == 50


def test_dedupe_by_timestamp_keeps_records_without_time():
    """回归：缺 time 字段的记录不能全塌进 timestamp=0 合并成一条。"""
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    items = [
        {"value": '{"steps": 20}'},
        {"value": '{"steps": 5}'},
        {"time": 100, "value": '{"steps": 30}'},
    ]

    deduped = adapter._dedupe_by_timestamp(items, "steps")

    # 三条互不相关的记录都要保留，不能被合成两条
    assert len(deduped) == 3
    assert sorted(adapter._parse_value(i)["steps"] for i in deduped) == [5, 20, 30]


def test_dedupe_by_timestamp_keeps_records_with_invalid_time():
    """回归：time 是非法值（None / 空串 / 非数字）时同样不能合并。"""
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    items = [
        {"time": None, "value": '{"steps": 7}'},
        {"time": "", "value": '{"steps": 9}'},
        {"time": "abc", "value": '{"steps": 11}'},
    ]

    deduped = adapter._dedupe_by_timestamp(items, "steps")

    assert len(deduped) == 3


@pytest.mark.asyncio
async def test_iter_daily_activity_does_not_double_count_multi_device_records(monkeypatch):
    """回归：同一分钟手机 + 手表各报一份时不能相加（2026-10-18 实测 29,370 → 14,606）。"""
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    adapter._connected = True
    adapter._client = object()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "steps":
            return [
                {"time": 1743467400, "zone_offset": 0, "value": '{"steps": 50, "distance": 40, "calories": 3}'},
                {"time": 1743467400, "zone_offset": 0, "value": '{"steps": 47, "distance": 37, "calories": 3}'},
                {"time": 1743467460, "zone_offset": 0, "value": '{"steps": 104, "distance": 82, "calories": 6}'},
                {"time": 1743467460, "zone_offset": 0, "value": '{"steps": 107, "distance": 85, "calories": 6}'},
                {"time": 1743467460, "zone_offset": 0, "value": '{"steps": 103, "distance": 81, "calories": 6}'},
            ]
        if key == "calories":
            return [
                {"time": 1743467400, "zone_offset": 0, "value": '{"calories": 5}'},
                {"time": 1743467400, "zone_offset": 0, "value": '{"calories": 4}'},
            ]
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    items = await _collect(adapter.iter_daily_activity("2025-04-01", "2025-04-01"))

    assert len(items) == 1
    # 50 + 107，而不是把 5 条全加起来得 411
    assert items[0].steps == 157
    assert items[0].distance_m == 125
    assert items[0].active_kcal == 5


@pytest.mark.asyncio
async def test_fetch_key_rejects_repeated_pagination_cursor(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._client = object()

    async def fake_request(base_url, api_path, payload):
        return {"data_list": [], "has_more": True, "next_key": "same"}

    monkeypatch.setattr(adapter, "_request", fake_request)
    with pytest.raises(RuntimeError, match="cursor loop"):
        await adapter._fetch_key("steps", "2026-07-06", "2026-07-12")


@pytest.mark.asyncio
async def test_connect_failure_closes_client(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="bad", region="cn")

    async def failed_login(user_id, pass_token):
        raise RuntimeError("invalid credentials")

    monkeypatch.setattr(adapter, "_login_with_token", failed_login)
    assert await adapter.connect() is False
    assert adapter._client is None
    assert "invalid credentials" in adapter.last_error


def test_authentication_error_detection():
    assert _is_authentication_error(401, "denied")
    assert _is_authentication_error(0, "session expired")
    assert _is_authentication_error(-10001, "unknown")
    assert not _is_authentication_error(500, "temporary server failure")
