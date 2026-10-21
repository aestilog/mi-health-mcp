# 收紧 sync_state 迁移的异常处理

> 状态：已修复（2026-10-21）
> 编写：2026-10-21
> 前置：commit `64ee383`（已删除 records_count 列并加迁移）

## 一、问题

`_drop_records_count_if_exists()` 目前这样写：

```python
with contextlib.suppress(sqlite3.OperationalError):
    conn.execute("ALTER TABLE sync_state DROP COLUMN records_count")
```

`sqlite3.OperationalError` 是个很宽的异常，至少覆盖三种完全不同的情况：

| 情况 | 是否该忽略 | 后果 |
|---|---|---|
| SQLite < 3.35，不支持 `DROP COLUMN` | **该忽略** | 列留着，功能无影响 |
| 该列被索引/视图/触发器依赖，删除被拒 | **不该忽略** | 列永远删不掉，但没人知道 |
| 库被锁（`database is locked`） | 可忽略 | 下次启动会再试 |

实测（本机 SQLite 3.46.1）：

```python
c.execute('CREATE TABLE t (a INTEGER, b TEXT, c INTEGER)')
c.execute('CREATE INDEX idx_b ON t(b)')
c.execute('ALTER TABLE t DROP COLUMN b')
# OperationalError: error in index idx_b after drop column: no such column: b
```

**现在这三种情况都静默通过**，如果真出现「删不掉」，代码会一直假装成功。

当前仓库没有任何索引涉及 `records_count`，所以线上不会触发。但这是「把失败伪装成成功」的模式，留着迟早坑人。

## 二、要求

改成**只忽略「不支持 DROP COLUMN」这一种**，其余情况正常抛错。

### 2.1 判断方式

不要靠匹配错误文本（SQLite 的报错措辞会变）。用版本判断：

```python
# DROP COLUMN 是 SQLite 3.35.0 引入的
SQLITE_MIN_VERSION_FOR_DROP_COLUMN = (3, 35, 0)

@staticmethod
def _drop_records_count_if_exists(conn: sqlite3.Connection) -> None:
    """老库迁移：删除已废弃的 records_count 列（恒为 0，无代码读写）。

    幂等：列不存在时静默跳过。
    SQLite < 3.35 不支持 DROP COLUMN，此时保留该列（无功能影响），
    其他异常（如列被索引依赖）不吞掉，让调用方知道迁移失败。
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sync_state)")}
    if "records_count" not in columns:
        return
    if sqlite3.sqlite_version_info < SQLITE_MIN_VERSION_FOR_DROP_COLUMN:
        logger.warning(
            "SQLite %s < 3.35, cannot drop sync_state.records_count; "
            "column left in place (harmless, no code reads it)",
            sqlite3.sqlite_version,
        )
        return
    conn.execute("ALTER TABLE sync_state DROP COLUMN records_count")
```

要点：
- 版本不够 → `logger.warning` 一次，然后返回，不抛错
- 版本够 → 直接 `execute`，**让异常自然抛出**，不 suppress
- `contextlib.suppress` 如果因此不再需要，把 `import contextlib` 也一并删掉（检查文件里其他地方有没有用到 `contextlib`；`from contextlib import contextmanager` 是另一回事，不要动）

### 2.2 logger

文件里如果没有模块级 `logger`，加一个：

```python
logger = logging.getLogger(__name__)
```

检查 `import logging` 是否已有，没有就加。

## 三、测试要求

在 `tests/test_storage_migration.py` 里补充：

1. **列被索引依赖时抛错** —— 手工建带 `records_count` 的表 + 对该列建索引，用 `Database(path)` 打开，断言抛 `sqlite3.OperationalError`（证明不再静默吞掉）
   - 注意：这条测试要构造「版本够但删除失败」的场景，不要 mock 版本
2. **原有 4 个测试仍然通过** —— 特别是老库迁移后数据完好那条

## 四、不要动的地方

- `update_sync_state()` / `get_sync_state()` / `server.py` 不动
- 其他表、其他索引不动
- 不要为了「让第 1 条测试过」而改成匹配错误字符串

## 五、验收标准

- `.venv/bin/pytest tests/ -q` 全部通过（当前 72 个）
- `.venv/bin/ruff check src/ tests/` 无错误
- 真实库 `~/.local/share/mi-fitness-mcp/mi_fitness.db` 打开不报错（该库的列**已经被删掉了**，走的是「列不存在直接返回」路径）

## 六、开发约束（必须遵守）

1. **只用项目已有的 `.venv/bin/python` 和 `.venv/bin/pytest`**
2. **绝对不要执行 `pip install`、`--break-system-packages`，不要碰系统 Python 或 `~/.local`**
3. 缺依赖就停下报告，不要自己装
4. 不要执行 `mi.py sync` 或任何联网同步操作
5. 不要修改 `~/.dsh`、`~/.hermes` 下的任何文件
6. **不要加 `Co-Authored-By` 之类的署名 trailer**
7. 一个 commit 完成
