#!/usr/bin/env python3
"""小米运动健康 CLI 桥接层。

作用：
  1. 从 ~/.config/secrets/xiaomi.env 读取 userId / passToken（凭据永远不进命令行参数、
     不进 shell history、不进聊天记录）；
  2. 把它们写进 keyring（headless 机器上用 keyrings.alt 的明文后端，文件本身 600 权限）；
  3. 补齐 config.json（region=cn、timezone=Asia/Shanghai），然后原样调用 mi-fitness-mcp。

用法：
  ./mi.py doctor
  ./mi.py sync --start-date 2026-09-01 --end-date 2026-10-19
  ./mi.py serve
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyrings.alt.file.PlaintextKeyring")

REPO = Path(__file__).resolve().parent

# 直接用 ./mi.py 跑时，系统 python 里没有项目依赖 —— 自动切到本仓库的 .venv
# 注意：不能比较 sys.executable，uv 建的 .venv/bin/python 是基础解释器的软链，resolve 后相同
_venv = REPO / ".venv"
_venv_python = _venv / "bin" / "python"
if (
    _venv_python.exists()
    and not os.environ.get("MI_FITNESS_REEXEC")
    and Path(sys.prefix).resolve() != _venv.resolve()
):
    os.environ["MI_FITNESS_REEXEC"] = "1"
    os.execv(str(_venv_python), [str(_venv_python), str(REPO / "mi.py"), *sys.argv[1:]])

sys.path.insert(0, str(REPO / "src"))

SECRET = Path(
    os.environ.get("MI_FITNESS_ENV_FILE", str(Path.home() / ".config" / "secrets" / "xiaomi.env"))
).expanduser()
SERVICE = "mi-fitness-mcp"


def read_secret() -> dict[str, str]:
    if not SECRET.exists():
        return {}
    values: dict[str, str] = {}
    for raw in SECRET.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def main() -> int:
    values = read_secret()
    user_id = values.get("XIAOMI_USER_ID", "")
    pass_token = values.get("XIAOMI_PASS_TOKEN", "")

    if not user_id or not pass_token:
        print("❌ 凭据未配置。")
        print(f"   请把 userId / passToken 写进：{SECRET}")
        print("   （浏览器登录 https://account.xiaomi.com → F12 → Application → Cookies →")
        print("     userId / passToken 两个值）填好后重新运行本命令。")
        return 2

    import keyring

    keyring.set_password(SERVICE, "mi_fitness_auth_user_id", user_id)
    keyring.set_password(SERVICE, "mi_fitness_auth_pass_token", pass_token)

    # 区域/时区只在缺失时补，避免覆盖用户手改过的其它配置
    import json

    from mi_fitness_mcp.config import get_config_path

    cfg_path = get_config_path()
    cfg: dict = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    changed = False
    if cfg.get("mode") != "mi_fitness_cloud":
        cfg["mode"] = "mi_fitness_cloud"
        changed = True
    if cfg.get("region") != "cn":
        cfg["region"] = "cn"
        changed = True
    if cfg.get("timezone") != "Asia/Shanghai":
        cfg["timezone"] = "Asia/Shanghai"
        changed = True
    if changed:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    from mi_fitness_mcp.cli_mi_fitness import main as cli_main

    sys.argv = ["mi-fitness-mcp", *sys.argv[1:]]
    cli_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
