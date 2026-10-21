# 睡眠数据三个问题的修复需求

> 状态：待实施
> 编写：2026-10-21
> 背景文档：`docs/issues/2026-10-20-sleep-data-issues.md`（初版，部分结论已被本文修正）

本文是交给开发 agent 的需求文档。**本文的数字全部来自实测**（365 天 448 条云端记录），与初版文档冲突时以本文为准。

---

## 一、总体要求

1. 三个问题分两个 commit：
   - **commit 1**：问题 1（分期映射）+ 问题 3（午睡识别）—— 只改解析层
   - **commit 2**：问题 2（同晚重复去重）
2. 每个问题都要有单元测试，测试必须能独立运行通过
3. 不要改动 `sync_state` 表结构、不要改 cron 配置
4. 修完后不要自己跑全量重新同步（由验收方执行）

---

## 二、问题 1：睡眠分期映射错误

### 2.1 现状

`src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` 的 `_sleep_stage_name`（约 442-453 行）：

```python
def _sleep_stage_name(self, state: Any) -> str:
    mapping = {
        1: "deep",
        2: "light",
        3: "light",
        4: "awake",
        5: "rem",
    }
    try:
        return mapping.get(int(state), "light")
    except Exception:
        return "light"
```

### 2.2 正确映射（已用数据验证）

| state | 正确含义 | 验证依据 |
|-------|---------|---------|
| 1 | **不存在** | 448 条记录中出现 0 次 |
| 2 | `deep` | 142 次精确等于 `sleep_deep_duration`（误差 ≤2 分钟） |
| 3 | `light` | 142 次精确等于 `sleep_light_duration`（误差 ≤2 分钟） |
| 4 | `rem` | 外部文档确认；且从不等于 `sleep_awake_duration`（0 次匹配） |
| 5 | `awake` | 14 次精确等于 `sleep_awake_duration`（14/14 全中） |
| 6 | `unclassified` | 89 条含 state 6 的记录，`deep` 与 `light` 字段**全部为 0**；时长与 `duration` 完全吻合 |

外部技术文档：`soma-intelligence/open-health-sync` → `docs/connectors/xiaomi.md` 第 7 节 Mapping，原文：
> with phases: `state` 2 deep, 3 light, 4 REM, 5 awake

### 2.3 要改的内容

**A. 映射表**

```python
mapping = {2: "deep", 3: "light", 4: "rem", 5: "awake", 6: "unclassified"}
```

- 删除 `1: "deep"`（无数据支撑）
- `2` 从 `light` 改为 `deep`
- `4` 从 `awake` 改为 `rem`
- `5` 从 `rem` 改为 `awake`
- `6` 新增为 `unclassified`

**B. 未知 state 的默认值**

现在默认返回 `"light"`，会把未知值伪装成浅睡。改为返回 `"unclassified"`，未知 state 也归入 `unclassified`，不要静默算成浅睡。

**C. 模型枚举**

`src/mi_fitness_mcp/models/__init__.py:39`：

```python
stage: Literal["deep", "light", "rem", "awake"]
```
改为
```python
stage: Literal["deep", "light", "rem", "awake", "unclassified"]
```

**D. `unclassified` 的语义（用户已确认方案 A）**

`unclassified` 表示「这段有睡眠，但设备没做分期分析」。查询时应返回为：

```json
"stages": [{"stage": "unclassified", "minutes": 321}]
```

**不要**返回空数组 —— 空数组无法与「整条记录没有任何 items」区分。

### 2.4 已知边界：items 各段之和可能超过 duration

实测 13 条记录 `items` 各段相加 > `duration`，最多多 63 分钟：

```
2026-08-22  dur=407  items=470  差 +63  {5:63, 6:407}
2026-07-21  dur=444  items=475  差 +31  {5:31, 6:444}
```

原因：`state 6` 那一段已经覆盖了整晚时长（含清醒），`state 5` 的清醒时间又被额外记了一段，导致重复。

**要求**：`duration_minutes` 必须继续用 payload 里的 `duration` 字段，**不要改成累加 items**。这个边界只需在测试里断言「stages 之和可以大于 duration_minutes，属正常」，不要试图修正数据。

### 2.5 测试要求

新增测试文件或在现有测试中补充，覆盖：

1. state 2 → `deep`，state 3 → `light`，state 4 → `rem`，state 5 → `awake`
2. state 6 → `unclassified`（且不等于 `light`）
3. state 1 和未知值（如 99、`None`、字符串 `"abc"`）→ `unclassified`，不抛异常
4. 一条只含 `[{state: 6, 321 分钟}]` 的记录，解析后 `stages == [{"stage": "unclassified", "minutes": 321}]`
5. 断言 `duration_minutes` 来自 payload 的 `duration`，不是累加值

### 2.6 验收标准

- 上述测试全部通过
- 全量重新同步后，`deep` 总量从 0 变为约 4,000+ 分钟
- 抽查 2026-10-20 夜（`hlth.gen` 那条 413 分钟记录）：`deep` 与 `light` 分别对上 payload 的 `sleep_deep_duration` / `sleep_light_duration`

---

## 三、问题 3：午睡未识别

### 3.1 现状

`is_nap` 恒为 `False`。代码里：

```python
is_nap=bool(payload.get("is_nap", False))
```

云端 `is_nap` 字段恒为 `null`，所以永远得到 `False`。

### 3.2 实测数据

365 天数据中，入睡时间在 11-16 点的记录 **184 条，全部来自手表设备直传（`749078412`）**，`hlth.gen` 一条都没有。

这些记录**全部没有 `items` 字段**（184 条中 0 条有分期），只有总时长。

时长分布：
```
0-30 分钟   154 条
30-60 分钟   27 条
60-90 分钟    1 条
90 分钟以上   2 条
```

### 3.3 判定规则

```
is_nap = (duration_minutes < 60) and (11 <= end_at 的本地小时 <= 16)
```

**注意**：用 `end_at` 的小时数，不是 `start_at`。因为入睡时间可能落在 11 点前，但醒来在 11-16 点之间。

时区必须用记录的 `zone_name`（实测为 `Asia/Shanghai`），不要用 UTC。

### 3.4 已知例外

有 6 条 `version: 4` 记录时长超过 60 分钟，最长 676 分钟（2026-08-01 19:48）。这条不是午睡，按上面的规则会正确判为 `False`（时长 > 60）。所以不要用 `version == 4` 作判据。

### 3.5 测试要求

1. `duration=25`、`end_at=13:30` → `is_nap=True`
2. `duration=25`、`end_at=03:30` → `is_nap=False`
3. `duration=120`、`end_at=13:30` → `is_nap=False`
4. `duration=59`、`end_at=11:00` → `is_nap=True`（边界）
5. `duration=59`、`end_at=16:59` → `is_nap=True`（边界）
6. `duration=59`、`end_at=17:00` → `is_nap=False`（边界）

### 3.6 验收标准

- 测试全部通过
- 全量重新同步后，184 条午睡时段记录中 `is_nap=True` 的 ≥ 150 条
- 夜间记录（20-09 点入睡）中 `is_nap=True` 的为 0 条

---

## 四、问题 2：同一晚重复入库

### 4.1 现状

初版文档记录「5 组重复」，**这个数字是错的**。那是只查了本地库里 176 条记录得出的。

拉取云端 365 天 448 条完整记录后，按「入睡时间相差 60 分钟内」分组，实际有 **21 组同一晚两条**。

### 4.2 两个来源的特征

| 来源 | sid 形态 | 条数 | 有 items | 说明 |
|------|---------|------|---------|------|
| 健康平台 | `hlth.gen_*` | 231 | 231（100%） | 只有 state 2/3/5/6，**没有 state 4** |
| 设备直传 | `749078412_*`（纯数字） | 217 | 20 | 有 state 4（REM），但 197 条无 items |

**设备规律（用户确认）**：晚上通常用手机记录（不戴手表入睡），午睡通常用手表记录。所以午睡 184 条全是设备直传，夜间 260 条中 231 条是健康平台。

**例外**：20 条带 REM 的夜间记录集中在 2025-10~11 月与 2026-07~08 月，说明这些时段用户戴表入睡。**代码里不要硬编码「手表只记午睡」这个规律。**

### 4.3 去重规则：按信息量排序（用户已确认）

不要按来源一刀切，按每条记录的信息量排序：

```
1. 有 state 4（REM）                    → 最高优先级
2. 有真实分期（state 2/3/5，不含 6）      → 次之
3. 无任何真实分期（state 6 或完全无 items）→ 最低，两档合并，只比 duration_minutes，更长者优先
```

**第 3 档为什么合并**：`state 6` 的语义是「这段睡眠没有做分期」，它的信息量和「完全无 items」**完全一样** —— 两者都只有总时长，没有深浅构成。`{6: 114}` 和「114 分钟无 items」等价，不能让前者因为多一个占位标记就压过后者。

实测反例（2026-05-24）：

```
设备直传   01:01  dur=161  无 items
健康平台   01:46  dur=114  {6: 114}
```

旧规则选 114 分钟那条，丢掉 161 分钟那条 —— 错的。state 6 不提供额外信息，就该比时长，161 > 114，选设备那条。

**同档内排序**：
- 第 1 档：先比 REM 分钟数（多者优先），再比 duration
- 第 2 档：先比真实分期的覆盖分钟数（多者优先），再比 duration
- 第 3 档：只比 duration

不要用入睡时间做同档的决胜键 —— 那会让「早睡的短记录」压过「晚睡的长记录」，与信息量无关。入睡时间只在完全平手时用于保证结果稳定。

### 4.4 21 组的实际结果

按上述规则，各组应保留：

| 组 | 日期 | 保留 | 理由 |
|---|------|------|------|
| 1-15 | 2025-10 ~ 2025-11 | 设备直传 | 有 REM |
| 16 | 2026-05-24 | 设备直传（161min 无分期） | 健康平台那条只有 state 6 的 114min |
| 17 | 2026-07-24 | 设备直传 | 有 REM |
| 18 | 2026-07-26 | 设备直传 | 有 REM |
| 19 | 2026-08-01 | 健康平台（state 6，121min） | 设备直传 114min 且无分期 |
| 20 | 2026-09-27 | 健康平台 | 有真实分期 |
| 21 | 2026-10-11 | 健康平台 | 有真实分期 |

### 4.5 实现要点

1. **去重发生在写入数据库前**，不要事后清理
2. 分组键：`start_at` 相差 ≤ 60 分钟的归为同一组
3. 同组内按 4.3 的优先级排序，保留第一条
4. 单条记录（无同组）原样保留
5. **不要修改已有的历史数据**，历史数据由验收方重新全量同步解决

### 4.6 测试要求

1. 两条记录都有 REM → 保留 REM 分钟数更多的那条
2. 一条有 REM、一条只有 state 2/3 → 保留有 REM 的
3. 一条有 state 2/3、一条只有 state 6 → 保留有 state 2/3 的
4. 两条都无 items → 保留 duration 更长的
5. `start_at` 相差 61 分钟 → 不合并，两条都保留
6. `start_at` 完全相同 → 合并为一条
7. 单条记录 → 原样返回
8. **一条只有 state 6（114min）、一条完全无 items（161min）→ 保留 161min 那条**（第 3 档合并，比时长）
9. **一条只有 state 6（121min）、一条完全无 items（114min）→ 保留 state 6 那条**（同样是比时长）
10. 两条都有真实分期但覆盖分钟数不同 → 保留覆盖更多的

### 4.7 验收标准

- 测试全部通过
- 全量重新同步后，任意两条记录 `start_at` 相差 ≤60 分钟的情况为 **0**
- 记录总数从 448 条降到约 427 条

---

## 五、相关代码位置

| 文件 | 位置 | 内容 |
|------|------|------|
| `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` | 442-453 | `_sleep_stage_name` 映射表 |
| `src/mi_fitness_mcp/adapters/mi_fitness_cloud.py` | 531-610 | `iter_sleep_sessions` 生成睡眠记录 |
| `src/mi_fitness_mcp/models/__init__.py` | 39 | `SleepStage.stage` 枚举 |
| `src/mi_fitness_mcp/services/query_service.py` | 152-187 | `get_sleep_sessions` 查询 |
| `src/mi_fitness_mcp/server.py` | 160-171 | `query_sleep` 工具定义 |
| `src/mi_fitness_mcp/storage/__init__.py` | 84 | `stages` 列定义 |

---

## 六、开发约束（必须遵守）

1. **只用项目已有的 `.venv/bin/python` 和 `.venv/bin/pytest`**
2. **绝对不要执行 `pip install`、`--break-system-packages`，不要碰系统 Python 或 `~/.local`**
3. 缺依赖就停下报告，不要自己装
4. 不要执行 `mi.py sync` 或任何联网同步操作
5. 不要修改 `~/.dsh`、`~/.hermes` 下的任何文件
6. 改完后运行 `.venv/bin/pytest tests/ -q` 确保全部通过（含已有的 26 个测试）

---

## 七、验收方式

开发完成后，验收方会：

1. 检查 `git diff`，确认只改了预期文件
2. 独立运行 `.venv/bin/pytest tests/ -q`
3. 独立运行 `ruff check src/ tests/`
4. 备份 `sync_state` 表后，手动执行全量重新同步
5. 对照第二节、第三节、第四节的验收标准逐条核对
