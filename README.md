# Mi Fitness MCP

小米运动健康 / Mi Fitness 数据本地 MCP Server。把云端数据同步到本地 SQLite，供 MCP 客户端或任何能读 SQLite 的工具查询。

独立维护，不跟踪任何上游分支。

## 参考与致谢

代码起源于下面两个项目，本项目在它们的实现基础上做了修正与扩展，之后独立演进：

| 项目 | 提供的基础 |
|---|---|
| [kubulashvili/mi-fitness-mcp](https://github.com/kubulashvili/mi-fitness-mcp) | 整体架构、MCP server、SQLite 存储层、认证流程（MIT） |
| [binglua/mi-fitness-mcp-cn](https://github.com/binglua/mi-fitness-mcp-cn) | 小米健康云接口逆向、`--region cn`、睡眠/运动记录、血氧/压力/异常心跳等扩展 key |

MIT 许可证与原始版权声明保留在 [LICENSE](LICENSE)。

## 与上游的关系

上游 `binglua/mi-fitness-mcp-cn` 最后一次 push 是 2026-07-13，已三个月无更新；[PR #1](https://github.com/binglua/mi-fitness-mcp-cn/pull/1)（`mcp<2` 依赖封顶）于 2026-09-27 开启后 23 天零评论、CI 停留在 `action_required`。同时已知有别人在 fork 里独立修了同一个 bug（`mochenya` 于 2026-10-19）。

本项目把修复集中在一处维护，不依赖上游是否合入，也不跟随上游更新。

## 相对参考实现做了什么

### 1. 修复步数 / 卡路里重复计数

小米健康云对同一天会返回多路上报记录（手机 + 手表各报一份）。实测 2026-10-18 共 353 条原始记录，但只有 176 个不同时间戳，同一分钟出现 2~3 条且数值不同。原实现把当天所有记录直接相加，等于把同一分钟走了两遍算两遍 —— 当天得 **29,370 步**，而小米运动 App 显示 **14,309**。

现在按时间戳合并、取最大值，同一天为 **14,606 步**。

> 剩余约 2% 的差异无法消除：小米 App 的活动段合并算法不等于「每分钟取最大值」。修复后的数字只能作量级参考，精确值仍以 App 为准。

规则见 `MiFitnessCloudAdapter._dedupe_by_timestamp`，回归测试见 `tests/test_mi_fitness_cloud.py`。

### 2. 依赖上限 `mcp<2`

`mcp` 2.x 移除了 `Server.list_tools`，装到 2.3.0 时 CLI 直接报 `AttributeError`。封顶为 `mcp>=1.0.0,<2`。

### 3. `mi.py`：headless 凭据桥接

无图形界面 / 无系统 keyring 的机器（服务器、容器、cron）上，从权限 600 的 env 文件读取 userId / passToken 写入 keyring，凭据不进命令行参数（否则会留在 shell history 和 `ps` 里）。它会自动 exec 进本仓库的 `.venv`。

### 4. 扩展数据指标

额外逆向并验证了以下云端 key，已接入 CLI 同步、SQLite 缓存和 MCP 查询工具：

- `resting_heart_rate`：静息心率，合并到 `query_heart_rate(sample_type="resting")`
- `spo2`：血氧饱和度，CLI 类型 `spo2`，MCP 工具 `query_spo2`
- `stress`：压力值，CLI 类型 `stress`，MCP 工具 `query_stress`
- `abnormal_heart_beat`：异常心跳事件，CLI 类型 `abnormal_heart_beat`，MCP 工具 `query_abnormal_heart_beat`

```bash
mi-fitness-mcp sync --type spo2 --start-date 2026-06-01 --end-date 2026-06-22
mi-fitness-mcp sync --type stress --start-date 2026-06-01 --end-date 2026-06-22
mi-fitness-mcp sync --type abnormal_heart_beat --start-date 2026-06-01 --end-date 2026-06-22
```

### 5. 凭据读取补环境变量兜底

`load_mi_fitness_token()` 现在优先读 keyring，缺失时回退到 `MI_FITNESS_USER_ID` / `MI_FITNESS_PASS_TOKEN` 环境变量。这两个变量在 `.env.example` 里写了很久，但过去全仓库没有一行代码读取它们 —— 照文档配好环境变量仍然会报找不到凭据。keyring 优先，`setup` 写入的值不会被环境变量覆盖。

### 6. 去重对缺 `time` 字段的记录兜底

`_dedupe_by_timestamp` 过去把 `time` 缺失或非法的记录一律归到 `timestamp=0` 这一个桶里，于是几条互不相关的记录被合并成一条、只留最大值，静默丢数据。现在这类记录按位置各自成组，原样保留。当前云端返回都带 `time`，实际没触发过，但接口一变更就会踩到。

## 已知限制

这些是当前实现的实际短板，不是待办清单 —— 记录在此，避免使用者踩到后误以为数据本身有问题。

### 数据可得性

| 项 | 现状 | 原因 |
|---|---|---|
| 体重 / 体成分 | 0 条 | 账号没有小米体脂秤，云端无数据。表结构和 MCP 工具都在，接上秤即可用 |
| 压力（stress） | 0 条 | 手环不上报该指标 |
| 睡眠得分 | 176 条全为空 | 云端 `sleep` 响应里没有 `score` 字段 |
| 深睡时长 | 恒为 0 | 云端 `state` 只返回 `2`/`3`，映射表里 `1=deep` 从未出现。睡眠分期实际只有 light / awake / rem 三档 |
| GPS 轨迹 | 无 | 只取了距离和步数，运动记录不含轨迹点 |

### 数据口径

- **步数存在约 2% 的系统性偏差**：小米 App 的活动段合并算法不等于「每分钟取最大值」。修复后的数字只能作量级参考，精确值以 App 为准。
- **午睡未被识别**：云端 `is_nap` 恒为 `false`，54 条 18~44 分钟的午睡（12–16 点开始）全部标成主睡眠。`query_sleep(include_naps=False)` 因此过滤不掉午睡 —— 要排除午睡只能按时长和开始时间自行判断。
- **睡眠按入睡日期归档**：23:40 入睡、次日 07:44 醒的记录归到入睡那天。查「昨天睡得怎样」要留意这个口径。

### 运维

- **`sync_state.records_count` 永远是 0**：列建了但没有写入逻辑。
- **无异常数据检测**：同步只负责搬运，不做合理性校验（比如某天步数突然翻十倍不会告警）。
- **CI 配置是 GitHub Actions**，仓库托管在自建 Gitea，实际不会触发。`pytest` / `ruff` 只能本地手动跑。

## 功能

- 读取小米运动健康云端数据
- 本地 SQLite 缓存
- MCP Server 支持
- 支持中国区：`--region cn`
- 支持数据类型：
  - `daily_activity`：步数、距离、活动卡路里
  - `heart_rate`：心率采样（含静息心率）
  - `sleep`：睡眠记录
  - `workouts`：运动记录
  - `body_measurements`：体重 / 身体成分，视账号数据而定
  - `spo2` / `stress` / `abnormal_heart_beat`：见上文

## 已逆向验证的接口

### 健康数据接口

```text
POST https://hlth.io.mi.com/app/v1/data/get_fitness_data_by_time
```

常用 key：

```text
steps
calories
heart_rate
weight
sleep
```

睡眠请求示例：

```json
{
  "start_time": 1767225600,
  "end_time": 1782086399,
  "key": "sleep"
}
```

### 运动记录接口

```text
POST https://hlth.io.mi.com/app/v1/data/get_sport_records_by_time
```

请求示例：

```json
{
  "start_time": 1767225600,
  "end_time": 1782086399,
  "limit": 50
}
```

返回字段通常包含 `sport_records`、`has_more`、`next_key`。

每条运动记录的 `value` 是 JSON 字符串，包含 `start_time`、`end_time`、`duration`、`distance`、`calories`、`avg_hrm`、`max_hrm` 等字段。

## 安装

```bash
git clone ssh://git@192.168.31.114:3022/uint/mi-fitness-mcp.git
cd mi-fitness-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

如果当前环境没有系统 keyring：

```bash
pip install -e '.[headless]'     # keyrings.alt，明文文件后端
```

注意：`keyrings.alt` 可能以明文文件方式保存凭据。

headless 服务器上推荐用 `mi.py`（会自动切到本仓库的 `.venv`）：

```bash
install -m 600 /dev/null ~/.config/secrets/xiaomi.env
# 写入两行：XIAOMI_USER_ID=... / XIAOMI_PASS_TOKEN=...
./mi.py doctor
./mi.py sync --start-date 2026-10-01 --end-date 2026-10-19
```

## 配置

需要从 `https://account.xiaomi.com` 登录后的 Cookie 中获取 `userId` 和 `passToken`。

中国区账号：

```bash
mi-fitness-mcp setup \
  --mode mi_fitness_cloud \
  --user-id "<userId>" \
  --pass-token "<passToken>" \
  --region cn
```

检查连接：

```bash
mi-fitness-mcp doctor
```

## 同步数据

```bash
# 全部可探测类型
mi-fitness-mcp sync --start-date 2026-01-01 --end-date 2026-06-21

# 按类型
mi-fitness-mcp sync --type daily_activity --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type heart_rate --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type sleep --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type workouts --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type body_measurements --start-date 2026-01-01 --end-date 2026-06-21
```

## 启动 MCP Server

```bash
mi-fitness-mcp serve
```

Claude Desktop 配置示例：

```json
{
  "mcpServers": {
    "mi-fitness": {
      "command": "mi-fitness-mcp",
      "args": ["serve"]
    }
  }
}
```

## MCP 工具

- `get_connection_status` — 检查连接状态
- `sync_data` — 触发同步（支持后台执行）
- `get_sync_status` — 查后台同步进度
- `get_profile` — 用户资料
- `get_daily_summary` — 某天的活动汇总
- `query_metric_series` — 任意指标时间序列
- `query_heart_rate` — 心率采样（含静息心率）
- `query_body_measurements` — 体重与体成分
- `query_sleep` — 睡眠记录
- `query_workouts` — 运动记录
- `query_spo2` — 血氧
- `query_stress` — 压力
- `query_abnormal_heart_beat` — 异常心跳事件
- `get_data_coverage` — 各类型数据覆盖范围

## 本地数据库

默认位置：

```text
~/.local/share/mi-fitness-mcp/mi_fitness.db
```

主要表：

```text
daily_activity
heart_rate_samples
sleep_sessions
workouts
body_measurements
sync_state
```

## 安全说明

- `passToken` 是敏感凭据，不要泄露。
- 不要提交本地配置、数据库、keyring 文件。
- 如果 token 泄露，建议退出小米账号并重新登录刷新。

## 与小米公司的关系

本项目与小米公司无关，非官方项目，仅用于读取和分析你自己的健康数据。

## 致谢

如果这两个项目的作者看到这里：这套东西的绝大部分工作是你们做的，本项目只是把几个具体的坑填上了。上游若恢复维护，下面几条都可以拆成独立 PR 送回去：

| 改动 | 适合的上游 | 备注 |
|---|---|---|
| 步数 / 卡路里重复计数修复 | `binglua/mi-fitness-mcp-cn` | 上游 issues 为 0，这个坑没人报过 |
| 环境变量兜底 | `binglua/mi-fitness-mcp-cn` | 顺带修掉 `.env.example` 的死变量 |
| `mcp<2` 封顶 | 已在 [PR #1](https://github.com/binglua/mi-fitness-mcp-cn/pull/1) | 不要重复开 |

## License

MIT。原始版权归 Aleksej Kubulashvili 所有，本项目的修改部分见 [LICENSE](LICENSE)。
