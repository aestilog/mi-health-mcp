# Changelog

## 0.1.0

首个版本。

### 数据接入

- 小米账号认证：`userId` + `passToken`
- 小米健康云（`hlth.io.mi.com`）数据同步到本地 SQLite
- 支持中国区（`--region cn`）
- 数据类型：步数 / 距离 / 活动卡路里、心率、静息心率、睡眠、运动记录、血氧、压力、异常心跳、体重与体成分（视账号数据而定）

### 可靠性修复

- **步数 / 卡路里重复计数**：云端对同一天返回多路上报记录（手机 + 手表各报一份），同一分钟出现 2~3 条。原实现直接相加，导致 2026-10-18 得到 29,370 步（App 显示 14,309）。改为按时间戳合并取最大值，同日为 14,606 步。剩余约 2% 差异来自 App 的活动段合并算法，量级可信、精确值以 App 为准。
- **去重对缺 `time` 字段兜底**：`time` 缺失或非法时不再全部塌进 `timestamp=0` 合并成一条，改为按位置各自成组，避免静默丢数据。
- **依赖上限 `mcp<2`**：`mcp` 2.x 移除了 `Server.list_tools`，装到 2.3.0 会直接 `AttributeError`。

### 凭据

- `load_mi_fitness_token()` 优先读 keyring，缺失时回退到 `MI_FITNESS_USER_ID` / `MI_FITNESS_PASS_TOKEN` 环境变量，无 keyring 后端的环境也能用。
- `mi.py`：headless 凭据桥接，从权限 600 的 env 文件读入凭据并写入 keyring，凭据不进命令行参数（避免留在 shell history 和 `ps` 里）。

### MCP 工具

`get_connection_status`、`sync_data`、`get_profile`、`get_daily_summary`、`query_metric_series`、`query_heart_rate`、`query_body_measurements`、`query_sleep`、`query_workouts`、`query_spo2`、`query_stress`、`query_abnormal_heart_beat`、`get_data_coverage`
