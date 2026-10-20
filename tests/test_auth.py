"""凭据读取：keyring 优先，缺失时回退到环境变量。"""

import keyring

from mi_fitness_mcp.auth import load_mi_fitness_token


def test_env_fallback_when_keyring_empty(monkeypatch):
    """回归：.env.example 里的 MI_FITNESS_USER_ID / MI_FITNESS_PASS_TOKEN 必须真的生效。"""
    monkeypatch.setattr(keyring, "get_password", lambda *a, **kw: None)
    monkeypatch.setenv("MI_FITNESS_USER_ID", "12345")
    monkeypatch.setenv("MI_FITNESS_PASS_TOKEN", "tok-from-env")

    assert load_mi_fitness_token() == ("12345", "tok-from-env")


def test_keyring_wins_over_env(monkeypatch):
    """keyring 里有值时不读环境变量，避免手改 env 覆盖 setup 写入的凭据。"""
    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda service, key: {"mi_fitness_auth_user_id": "999", "mi_fitness_auth_pass_token": "tok-kr"}.get(key),
    )
    monkeypatch.setenv("MI_FITNESS_USER_ID", "12345")
    monkeypatch.setenv("MI_FITNESS_PASS_TOKEN", "tok-from-env")

    assert load_mi_fitness_token() == ("999", "tok-kr")


def test_keyring_unavailable_falls_back_to_env(monkeypatch):
    """没有 keyring 后端时（headless）不能直接失败，要降级到环境变量。"""

    def boom(*a, **kw):
        raise RuntimeError("no keyring backend")

    monkeypatch.setattr(keyring, "get_password", boom)
    monkeypatch.setenv("MI_FITNESS_USER_ID", "12345")
    monkeypatch.setenv("MI_FITNESS_PASS_TOKEN", "tok-from-env")

    assert load_mi_fitness_token() == ("12345", "tok-from-env")


def test_returns_none_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda *a, **kw: None)
    monkeypatch.delenv("MI_FITNESS_USER_ID", raising=False)
    monkeypatch.delenv("MI_FITNESS_PASS_TOKEN", raising=False)

    assert load_mi_fitness_token() == (None, None)
