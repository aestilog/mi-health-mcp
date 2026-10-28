# Mi Fitness MCP

小米运动健康 / Mi Fitness 数据本地 MCP Server。把云端数据同步到本地 SQLite，供 MCP 客户端或任何能读 SQLite 的工具查询。

## 功能

- 读取小米运动健康云端数据，同步到本地 SQLite 缓存
- 提供 MCP Server（stdio），供 Claude Desktop 等 MCP 客户端调用
- 支持中国区（`--region cn`），其它区域可选 `ru` / `de` / `i2` / `sg` / `us`
- 支持的数据类型：

| 类型 | 内容 |
|---|---|
| `daily_activity` | 步数、距离、活动卡路里 |
| `heart_rate` | 心率采样（主动 / 被动）与静息心率 |
| `sleep` | 睡眠记录（分期、午睡、同晚去重） |
| `workouts` | 运动记录 |
| `body_measurements` | 体重 / 身体成分，视账号设备而定 |
| `spo2` | 血氧饱和度 |
| `stress` | 压力值 |
| `abnormal_heart_beat` | 异常心跳事件 |

## 数据处理

### 步数与卡路里

云端对同一天会返回多路上报记录（手机 + 手表各报一份），同一分钟常见 2~3 条且数值不同。同步时按时间戳合并、取最大值，再按天累加，而不是把所有记录直接相加。

> 剩余约 2% 的差异无法消除：小米 App 的活动段合并算法不等于「每分钟取最大值」。数字只能作量级参考，精确值仍以 App 为准。

### 睡眠

- **分期映射**：`state` 2 → deep、3 → light、4 → rem、5 → awake、6 → unclassified（设备未做分期分析），未知值一律归入 unclassified。
- **同晚去重**：入睡时间相差 ≤60 分钟的记录视为同一晚（健康平台与设备直传各记一份），只保留信息量最高的一条 —— 含 REM 的优先，其次是有真实分期的，最后是只有总时长的；同档比较时长。
- **午睡识别**：时长 <60 分钟且醒来时间落在本地 11:00–16:59 的记录标记为 `is_nap`。
- **归档口径**：按入睡日期归档。23:40 入睡、次日 07:44 醒的记录归到入睡那天，查「昨天睡得怎样」时需留意。

### 缺时间戳的记录

`time` 缺失或非法的记录不参与时间戳合并，各自原样保留，不会被合并成一条。

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

凭据也可以通过环境变量提供，适合容器 / cron / 无 keyring 的环境：

```bash
export MI_FITNESS_USER_ID="<userId>"
export MI_FITNESS_PASS_TOKEN="<passToken>"
```

keyring 优先：`setup` 写入的值不会被环境变量覆盖。变量说明见 [.env.example](.env.example)。

检查连接：

```bash
mi-fitness-mcp doctor
```

## 同步数据

```bash
# 全部支持的类型
mi-fitness-mcp sync --start-date 2026-01-01 --end-date 2026-06-21

# 按类型
mi-fitness-mcp sync --type daily_activity --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type heart_rate --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type sleep --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type workouts --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type body_measurements --start-date 2026-01-01 --end-date 2026-06-21
mi-fitness-mcp sync --type spo2 --start-date 2026-06-01 --end-date 2026-06-22
mi-fitness-mcp sync --type stress --start-date 2026-06-01 --end-date 2026-06-22
mi-fitness-mcp sync --type abnormal_heart_beat --start-date 2026-06-01 --end-date 2026-06-22
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

| 工具 | 用途 |
|---|---|
| `get_connection_status` | 检查连接状态 |
| `sync_data` | 触发同步（支持后台执行） |
| `get_sync_status` | 查后台同步进度 |
| `get_profile` | 用户资料 |
| `get_daily_summary` | 某天的活动汇总 |
| `query_metric_series` | 任意指标时间序列 |
| `query_heart_rate` | 心率采样（含静息心率） |
| `query_body_measurements` | 体重与体成分 |
| `query_sleep` | 睡眠记录 |
| `query_workouts` | 运动记录 |
| `query_spo2` | 血氧 |
| `query_stress` | 压力 |
| `query_abnormal_heart_beat` | 异常心跳事件 |
| `get_data_coverage` | 各类型数据覆盖范围 |

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
spo2_samples
stress_samples
abnormal_heart_beat_events
sync_state
```

## 已知限制

这些是当前实现的实际短板，不是待办清单 —— 记录在此，避免使用者踩到后误以为数据本身有问题。

### 数据可得性

| 项 | 现状 | 原因 |
|---|---|---|
| 体重 / 体成分 | 0 条 | 账号没有小米体脂秤，云端无数据。表结构和 MCP 工具都在，接上秤即可用 |
| 压力（stress） | 0 条 | 手环不上报该指标 |
| 睡眠得分 | 全为空 | 云端 `sleep` 响应里没有 `score` 字段 |
| GPS 轨迹 | 无 | 只取了距离和步数，运动记录不含轨迹点 |

### 数据口径

- **步数存在约 2% 的系统性偏差**：小米 App 的活动段合并算法不等于「每分钟取最大值」，数字只能作量级参考，精确值以 App 为准（见上文「数据处理」）。

### 运维

- **无异常数据检测**：同步只负责搬运，不做合理性校验（比如某天步数突然翻十倍不会告警）。
- **CI 只在本仓库推送到 GitHub 时触发**：本地可用 `pytest` / `ruff` 手动跑。

## 云端接口

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

## 安全说明

- `passToken` 是敏感凭据，不要泄露。
- 不要提交本地配置、数据库、keyring 文件。
- 如果 token 泄露，建议退出小米账号并重新登录刷新。

## 与小米公司的关系

本项目与小米公司无关，非官方项目，仅用于读取和分析你自己的健康数据。

## 参考与致谢

代码起源于以下两个项目，感谢它们的作者与维护者：

| 项目 | 提供的基础 |
|---|---|
| [kubulashvili/mi-fitness-mcp](https://github.com/kubulashvili/mi-fitness-mcp) | 整体架构、MCP server、SQLite 存储层、认证流程（MIT） |
| [binglua/mi-fitness-mcp-cn](https://github.com/binglua/mi-fitness-mcp-cn) | 小米健康云接口逆向、`--region cn`、睡眠/运动记录、血氧/压力/异常心跳等扩展 key |

MIT 许可证与原始版权声明保留在 [LICENSE](LICENSE)。

## License

MIT。完整许可证与版权声明见 [LICENSE](LICENSE)。
