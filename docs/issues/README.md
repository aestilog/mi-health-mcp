# 问题记录

本目录记录项目在运行中发现的数据正确性问题。每条记录包含：现象、根因、取证方法、实测数据、修复方向、验收标准。

## 待修复

（无）

## 已修复

| 日期 | 问题 | 说明 |
|------|------|------|
| 2026-10-21 | `sync_state.records_count` 死字段 | 该列从未被写入（恒为 0），全仓库无人读。已从建表语句删除，并加老库迁移（`PRAGMA table_info` 检测 + `ALTER TABLE DROP COLUMN`）。见 [2026-10-21-drop-records-count.md](2026-10-21-drop-records-count.md)，commit `64ee383` |
| 2026-10-21 | 迁移异常处理过宽 | 初版用 `contextlib.suppress(sqlite3.OperationalError)`，把「列被索引依赖导致删除失败」也静默吞掉。改为按 `sqlite3.sqlite_version_info` 判断版本，版本够时让异常正常抛出。见 [2026-10-21-tighten-migration-error-handling.md](2026-10-21-tighten-migration-error-handling.md)，commit `eeafedb` |
| 2026-10-21 | 睡眠数据三个问题 | 分期映射错误（state 2/4/5 全错、state 6 落入浅睡）、同晚健康平台与设备直传重复入库（21 组）、午睡全部未识别。修复见 [2026-10-21-sleep-fix-spec.md](2026-10-21-sleep-fix-spec.md)，实施 commit `57a8779` + `7030696`。全量重同步后 427 条，deep 从 0 → 11,511 分钟，`is_nap` 从 0 → 180 条 |
| 2026-10-19 | 步数重复累加 | 同一分钟手机与手表两路各报一份被相加，按时间戳去重取最大值。修复后 2026-10-18 从 29,370 步修正为 14,606 步。剩余约 2% 偏差源于小米 App 活动段合并算法差异，无法修复，已在 README 标注为「量级可信、精确值以 App 为准」 |
| 2026-10-20 | `_dedupe_by_timestamp` 缺 `time` 字段时塌陷 | 3 条输入中有 2 条缺 `time`，全部塌成 `timestamp=0` 被合并。改为缺 `time`/非法 `time` 时按位置各自成组，已加回归测试 |
| 2026-10-20 | 依赖未封顶导致崩溃 | `mcp>=1.0.0` 会装到 2.x，而 2.x 移除了 `Server.list_tools`，报 `Server object has no attribute list_tools`。已封顶为 `mcp>=1.0.0,<2` |
| 2026-10-20 | headless 环境凭据加载失败 | `load_mi_fitness_token()` 改为 keyring 优先、缺失或异常时回退 `MI_FITNESS_USER_ID` / `MI_FITNESS_PASS_TOKEN`，都没配返回 `None`。已加 4 个测试 |

## 历史文档

| 文档 | 说明 |
|------|------|
| [2026-10-20-sleep-data-issues.md](2026-10-20-sleep-data-issues.md) | 睡眠三个问题的初版取证。部分结论已被 [2026-10-21-sleep-fix-spec.md](2026-10-21-sleep-fix-spec.md) 修正（重复组数 5 → 21、去重规则从「来源优先」改为「信息量优先」），数字以新文档为准 |

## 记录约定

- 文件名格式：`YYYY-MM-DD-<主题>.md`
- 必须包含可复现的取证命令，不能只有结论
- 数字必须是实测的，注明统计窗口和样本量
- 修复后不删文档，移到「已修复」并补充修复方式
