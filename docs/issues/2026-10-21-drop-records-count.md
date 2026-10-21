# 删除 sync_state.records_count 列

> 状态：已修复（2026-10-21）
> 编写：2026-10-21

## 一、问题

`sync_state` 表有一列 `records_count INTEGER DEFAULT 0`，但它**从来没有被写入过**，永远是 0。

### 1.1 取证

```bash
$ grep -rn "records_count" src/ tests/
src/mi_fitness_mcp/storage/__init__.py:228:    records_count INTEGER DEFAULT 0
```

**全仓库只有建表语句这一处提到它**，没有任何代码读或写。

`update_sync_state()` 的 INSERT 明确只写三列：

```python
INSERT INTO sync_state (data_type, last_sync_at, last_record_timestamp)
VALUES (?, CURRENT_TIMESTAMP, ?)
ON CONFLICT(data_type) DO UPDATE SET
    last_sync_at = CURRENT_TIMESTAMP,
    last_record_timestamp = excluded.last_record_timestamp
```

不写 `records_count`，所以每次插入都用建表时的 `DEFAULT 0`。

### 1.2 影响

无功能影响 —— 没有任何代码读它，MCP 工具不返回它，`get_connection_status` 只用 `last_sync_at`。它是纯死字段。

## 二、要求

**删除 `records_count` 列**，包括：
1. 从 `CREATE TABLE sync_state` 建表语句中移除
2. 为已存在的老库加兼容处理（已有库的表里还留着这一列）

## 三、实现要求

### 3.1 建表语句

`src/mi_fitness_mcp/storage/__init__.py` 约 222–230 行：

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS sync_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_type TEXT NOT NULL UNIQUE,
        last_sync_at TIMESTAMP,
        last_record_timestamp TIMESTAMP
    )
""")
```

删掉 `records_count INTEGER DEFAULT 0` 那一行（注意前一行末尾的逗号也要去掉）。

### 3.2 老库兼容

`CREATE TABLE IF NOT EXISTS` 对已存在的表**不会改动结构**，所以老库里的 `records_count` 列还在。需要加一段迁移。

要求：
- 放在 `_init_db()` 里，建表语句之后
- 检测 `sync_state` 表是否有 `records_count` 列，有则删除
- 用 `PRAGMA table_info(sync_state)` 检测列是否存在
- 用 `ALTER TABLE sync_state DROP COLUMN records_count` 删除（本机 SQLite 3.46.1 支持，`DROP COLUMN` 需要 3.35+）
- **必须是幂等的** —— 重复调用不能报错，列已经不存在时静默跳过
- 用 `contextlib.suppress` 或 try/except 兜底，避免 SQLite 版本过老时启动失败

参考写法（具体实现你自己定，只要满足上面的要求）：

```python
def _drop_records_count_if_exists(conn) -> None:
    """老库迁移：删除已废弃的 records_count 列（恒为 0，无代码读写）。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sync_state)")}
    if "records_count" not in columns:
        return
    conn.execute("ALTER TABLE sync_state DROP COLUMN records_count")
```

### 3.3 不要动的地方

- `update_sync_state()` 不动（它本来就没写这列）
- `get_sync_state()` 不动（`SELECT *` 自动少一列，调用方都没用它）
- `server.py` 的 `get_connection_status` 不动
- 其他任何表不动

## 四、测试要求

新增 `tests/test_storage_migration.py`（或加到已有的 `tests/test_storage_query.py`）：

1. **新库不含该列** —— 新建 `Database(tmp_path / "x.db")`，`PRAGMA table_info(sync_state)` 里没有 `records_count`
2. **老库能迁移** —— 手工建一个带 `records_count` 列的 `sync_state` 表（模拟老库），写入几行数据，然后用 `Database(path)` 打开，确认列已删除、**原有数据还在**（`data_type` / `last_sync_at` / `last_record_timestamp` 三列的值不变）
3. **幂等** —— 对同一个库连续 `Database(path)` 两次，不报错
4. **新库建表后再打开一次** —— 不报错（覆盖「列不存在时迁移逻辑静默跳过」的路径）

## 五、验收标准

- `.venv/bin/pytest tests/ -q` 全部通过（当前 68 个）
- `.venv/bin/ruff check src/ tests/` 无错误
- 用真实库 `~/.local/share/mi-fitness-mcp/mi_fitness.db` 打开一次，`PRAGMA table_info(sync_state)` 不再有 `records_count`，且原有 8 行数据完好

## 六、开发约束（必须遵守）

1. **只用项目已有的 `.venv/bin/python` 和 `.venv/bin/pytest`**
2. **绝对不要执行 `pip install`、`--break-system-packages`，不要碰系统 Python 或 `~/.local`**
3. 缺依赖就停下报告，不要自己装
4. 不要执行 `mi.py sync` 或任何联网同步操作
5. 不要修改 `~/.dsh`、`~/.hermes` 下的任何文件
6. **不要加 `Co-Authored-By` 之类的署名 trailer**
7. 不要新建 commit 之外的任何操作，改完一个 commit 即可
