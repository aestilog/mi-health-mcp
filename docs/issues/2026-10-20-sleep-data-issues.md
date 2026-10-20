# 睡眠数据问题记录

> 状态：待修复
> 记录日期：2026-10-20
> 数据来源：小米运动健康云端 API（`hlth.io.mi.com`），非官方逆向接口
> 本地库：`~/.local/share/mi-fitness-mcp/mi_fitness.db`

本文记录 `sleep_sessions` 表当前存在的三个数据正确性问题，按严重程度排序。每个问题都附有可复现的取证方法和实测数字，供后续修复时对照验收。

---

## 摘要

| # | 问题 | 影响 | 严重度 |
|---|------|------|--------|
| 1 | 睡眠分期映射表错误（3 个 state 全错） | 深睡恒为 0、REM 记成清醒、无分期数据记成浅睡 | **高** |
| 2 | 同一晚重复入库（双来源） | 5 组重复，平均睡眠时长被重复计入 | **高** |
| 3 | 午睡记录混入主睡眠 | 64 条 20 分钟左右的午睡被当作夜间睡眠 | 中 |

三个问题互相独立，可分别修复、分别验收。

---

## 问题 1：睡眠分期映射表错误

### 现象

库中 `stages` 字段的汇总结果：

```
deep      0 分钟
light 40577 分钟
rem     206 分钟
awake   219 分钟
```

`deep` 恒为 0，`light` 占了 99%。而小米 App 里显示每晚都有深睡。

### 根因

`src/mi_fitness_mcp/adapters/mi_fitness_cloud.py:442-453`：

```python
def _sleep_stage_name(self, state: Any) -> str:
    mapping = {
        1: "deep",
        2: "light",     # ← 错，2 是深睡
        3: "light",
        4: "awake",     # ← 错，4 是 REM
        5: "rem",       # ← 错，5 是清醒
    }
    try:
        return mapping.get(int(state), "light")   # ← 错，未匹配的 6 也落到 light
    except Exception:
        return "light"
```

### 取证：state 的真实含义

拉取 120 天共 191 条原始 payload，按 `state` 汇总分钟数，与同一条记录里的 `sleep_deep_duration` / `sleep_light_duration` / `sleep_awake_duration` 字段逐一对照：

| state | 120 天总分钟 | 段数 | 真实含义 | 判定依据 |
|-------|-------------|------|---------|---------|
| 2 | 4,256 | 288 | **深睡 deep** | 与 `sleep_deep_duration` 逐条吻合 |
| 3 | 15,761 | 352 | **浅睡 light** | 与 `sleep_light_duration` 逐条吻合 |
| 4 | 219 | 21 | **REM** | 与 `sleep_rem_duration` 逐条吻合 |
| 5 | 221 | 18 | **清醒 awake** | 与 `sleep_awake_duration` 逐条吻合 |
| 6 | 23,133 | 81 | **无分期数据** | 对应记录 deep/light 字段全为 0 |

**对照校验结果：124 条可比对记录中，state 2 ≈ `sleep_deep_duration`、state 3 ≈ `sleep_light_duration` 偏差超过 2 分钟的：0 条。**

单条原始样本（2026-10-20 夜）：

```
sid: hlth.gen_143720154401061
  duration: 413
  sleep_deep_duration: 70
  sleep_light_duration: 343
  segments: 11
    state 2: 70 分钟     ← 正好等于 sleep_deep_duration
    state 3: 342 分钟    ← 正好等于 sleep_light_duration
```

### 三个错误的具体后果

| state | 现在映射成 | 应该映射成 | 后果 |
|-------|-----------|-----------|------|
| 2 | `light` | `deep` | **4,256 分钟真实深睡被算成浅睡** |
| 4 | `awake` | `rem` | 219 分钟 REM 被算成清醒 |
| 5 | `rem` | `awake` | 221 分钟清醒被算成 REM |
| 6 | `light` | 不计入 / `unknown` | **23,133 分钟无分期数据被算成浅睡** |

state 6 占比最大（23,133 分钟，超过总量的一半）。这些记录的特征是：

- `sleep_deep_duration`、`sleep_light_duration`、`sleep_awake_duration` 三个字段全部为 0
- 66 条含 state 6 的记录中，有分期值的：0 条

也就是说，**state 6 是设备没做分期的整段睡眠**。把它算成 `light` 会让「浅睡占比」这个指标彻底失真。

### 修复方向

1. 修正映射表：`2→deep`、`4→rem`、`5→awake`
2. state 6 不应归入任何真实分期，建议：
   - 新增 `unknown` 阶段，或
   - 直接跳过该段，只保留 `duration_minutes` 总量
3. 补测试：至少覆盖 5 个 state 各自的映射结果，以及 state 6 的处理

### 验收标准

- 修复后重新同步，`deep` 总量应约为 4,000+ 分钟（而非 0）
- `rem` 与 `awake` 的数值应互换后各自落在 200 分钟量级
- 新增的映射测试全部通过
- 抽查 2026-10-20 夜：`deep=70`、`light=343`（当前库中该条是 `light=413`）

---

## 问题 2：同一晚重复入库

### 现象

176 条 `sleep_sessions` 记录中有 **5 组是同一晚的两条记录**：

| 日期 | 记录 A | 记录 B |
|------|--------|--------|
| 2026-07-24 | `hlth.gen_…_1784847315` 374min | `749078412_1784847300` 372min |
| 2026-07-25/26 | `749078412_1785008100` 240min | `hlth.gen_…_1785014694` 311min |
| 2026-08-01 | `hlth.gen_…_1785524456` 121min | `749078412_1785524400` 114min |
| 2026-09-27 | `749078412_1790465580` 180min | `hlth.gen_…_1790465478` 171min |
| 2026-10-11 | `749078412_1791663000` 168min | `hlth.gen_…_1791663489` 141min |

### 根因

小米云端对同一晚从两个来源各返回一份记录，`sid` 分两种形态：

- `hlth.gen_143720154401061_<time>` —— 健康平台生成
- `749078412_<time>` —— 设备直传

代码按 `{sid}_{time}` 拼 `sleep_id`，两个来源天然不同，`INSERT` 时不会冲突，于是两条都进了库。

**注意：这与已修复的步数重复是同一类缺陷**（多来源重复上报），但步数那次是「同一分钟两路各报一份」，睡眠这次是「同一晚两份完整记录」，粒度不同。

### 关键数据：两个来源的数据质量差异很大

| 来源 | 记录数 | 有分期数据 | 无分期 | 总时长 |
|------|--------|-----------|--------|--------|
| `hlth.gen_*` | 112 | **112（100%）** | 0 | 39,569 分钟 |
| 纯数字 `749078412_*` | 64 | 3（5%） | **61** | 3,147 分钟 |

`hlth.gen_*` 来源的分期数据是完整可靠的；纯数字来源 95% 没有分期。

### 修复方向

按「同一晚」分组去重，保留规则建议：

1. **优先保留分期数据完整的记录**（`hlth.gen_*` 来源）
2. 分期都完整或都不完整时，保留 `duration_minutes` 更长的
3. 判定「同一晚」的窗口：两条记录 `start_at` 相差 60 分钟内（实测 5 组重复的间隔在 4 分钟到 38 分钟之间）

### 待确认

去重保留规则需要产品决策：

- **方案 A（推荐）**：保留分期更完整的（`hlth.gen_*`），时长可能略短
- **方案 B**：保留时长更长的，即使没有分期数据

方案 A 更符合「数据质量优先」，但会在 2026-07-24 那种 A 有分期、B 无分期的情况下丢掉一点时长。

### 验收标准

- 去重后 `sleep_sessions` 从 176 条降到 171 条
- 上述 5 组每组只剩 1 条
- 新增去重测试，覆盖「两侧都有分期」「两侧都无分期」「只有一侧有分期」三种情况
- 全库复核：任意两条记录 `start_at` 相差不超过 60 分钟的情况为 0

---

## 问题 3：午睡记录混入主睡眠

### 现象

64 条 `version: 4` 且时长 < 60 分钟的记录，起床时间分布：

```
13 点: ██████████████████████████████████████████████████████████ (58)
03 点: █ (1)
05 点: █ (1)
10 点: █ (1)
14 点: █ (1)
16 点: █ (1)
```

**58/64 集中在 13 点前后**，时长 20 分钟左右——这是午睡，不是夜间睡眠。

### 根因

云端 `is_nap` 字段恒为 `null`（不可靠），代码里 `is_nap=bool(payload.get("is_nap", False))` 永远得到 `False`。所有记录不分昼夜全部当作夜间睡眠入库。

### 为什么不能直接用 `version == 4` 判定午睡

`version: 4` 共 70 条，其中 6 条时长超过 60 分钟，最长 676 分钟（2026-08-01 19:48）。所以 **`version` 不是可靠的午睡判据**。

### 可用的判据

实测数据支持两个特征组合：

| 特征 | 午睡 | 夜间睡眠 |
|------|------|---------|
| `duration_minutes` | 15~30 分钟 | 通常 > 120 分钟 |
| 起床时间 | 集中在 12~14 点 | 集中在 6~9 点 |
| `segments` 数 | 多为 0 | 通常有 |

建议判定规则：`duration_minutes < 60` **且** `end_at` 的小时数在 11~16 之间。

### 修复方向

1. 用上述规则设置 `is_nap=True`，而不是依赖云端字段
2. 午睡记录应可在查询时排除（例如 `query_sleep` 增加 `include_nap` 参数，默认 `False`）
3. 不要在入库时丢弃午睡数据——它本身是有价值的，只是不该混进夜间睡眠统计

### 验收标准

- 64 条短记录中，`is_nap=True` 的应 ≥ 58 条（13 点那批）
- 夜间睡眠记录中 `is_nap=True` 的应为 0
- `query_sleep` 默认排除午睡后，最近 30 天平均睡眠时长应上升（当前被午睡稀释）

---

## 复现方法

### 拉原始 payload

```bash
cd ~/proj/mi-fitness-mcp-cn
.venv/bin/python - <<'EOF'
import sys, asyncio
from datetime import date, timedelta
sys.path.insert(0, "src")
from mi_fitness_mcp.auth import load_mi_fitness_token
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter

uid, pt = load_mi_fitness_token()

async def main():
    a = MiFitnessCloudAdapter(user_id=uid, pass_token=pt, region="cn")
    await a.connect()
    end = date.today(); start = end - timedelta(days=120)
    recs = await a._fetch_key("sleep", start.isoformat(), end.isoformat())
    for item in recs[-5:]:
        p = a._parse_value(item)
        print(item.get("sid"), p.get("version"), p.get("duration"),
              p.get("sleep_deep_duration"), p.get("sleep_light_duration"))

asyncio.run(main())
EOF
```

### 查库中分期汇总

```bash
.venv/bin/python - <<'EOF'
import sqlite3, os, json
from collections import Counter
db = os.path.expanduser("~/.local/share/mi-fitness-mcp/mi_fitness.db")
cur = sqlite3.connect(db).cursor()
cur.execute("SELECT stages FROM sleep_sessions WHERE stages IS NOT NULL AND stages != ''")
tot = Counter()
for (s,) in cur.fetchall():
    for item in json.loads(s):
        tot[item.get("stage")] += item.get("minutes", 0)
print(tot)
EOF
```

---

## 注意事项

### `region` 默认值是 `ru`

`MiFitnessCloudAdapter.__init__` 的签名是 `region: str = "ru"`。如果构造时没显式传 `region="cn"`，所有数据请求会打到俄罗斯区接口，返回 0 条记录。

上面的复现脚本都显式传了 `region="cn"`。如果发现拉不到数据，先查这个。

### 测试时的副作用

上一轮排查时用 `--start-date 2025-01-01` 做回溯测试，把 `sync_state.daily_activity.last_record_timestamp` 污染成了 `2025-01-31`，导致后续增量同步失效。

修复本次问题后如果重新同步，注意检查：

```bash
.venv/bin/python -c "
import sqlite3, os
db = os.path.expanduser('~/.local/share/mi-fitness-mcp/mi_fitness.db')
cur = sqlite3.connect(db).cursor()
cur.execute('SELECT data_type, last_record_timestamp FROM sync_state')
for r in cur.fetchall(): print(r)
"
```

`daily_activity` 的 `last_record_timestamp` 应接近当天日期，不应是历史日期。

---

## 修复顺序建议

1. **先修问题 1（分期映射）** —— 改动最小，收益最直接，且是纯函数级修改，风险低
2. **再修问题 3（午睡识别）** —— 同样是解析层改动，但需要先定判据阈值
3. **最后修问题 2（去重）** —— 涉及「保留哪条」的产品决策，且要去重历史数据，风险最高

问题 1 和 3 可以一起改，都只动解析层；问题 2 单独一个 commit，因为它要处理历史数据清理。

---

## 附：相关代码位置

| 文件 | 位置 | 内容 |
|------|------|------|
| `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` | 442-453 | `_sleep_stage_name()` 映射表 |
| `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` | 531-601 | `iter_sleep_sessions()` 主解析逻辑 |
| `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` | 599 | `is_nap=bool(payload.get("is_nap", False))` |
| `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` | 583 | `sleep_id` 拼接方式（重复问题根源） |
| `src/mi_fitness_mcp/server.py` | 547-575 | `query_sleep` MCP 工具 |
| `tests/test_mi_fitness_cloud.py` | — | 现有测试，无睡眠分期覆盖 |
