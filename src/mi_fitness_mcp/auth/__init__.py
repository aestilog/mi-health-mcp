"""Authentication helpers for Mi Fitness cloud API."""

import logging
import os

import keyring

logger = logging.getLogger(__name__)


SERVICE_NAME = "mi-fitness-mcp"
ACCOUNT_NAME = "mi_fitness_auth"

# 环境变量兜底：容器 / cron / CI 这类没有系统 keyring 的环境用这个
ENV_USER_ID = "MI_FITNESS_USER_ID"
ENV_PASS_TOKEN = "MI_FITNESS_PASS_TOKEN"


def save_mi_fitness_token(user_id: str, pass_token: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, f"{ACCOUNT_NAME}_user_id", user_id)
        keyring.set_password(SERVICE_NAME, f"{ACCOUNT_NAME}_pass_token", pass_token)
    except Exception as exc:
        logger.error("Failed to save Mi Fitness credentials: %s", exc)
        raise


def load_mi_fitness_token() -> tuple[str | None, str | None]:
    """读取凭据：优先 keyring，缺失时回退到环境变量。

    环境变量兜底让 ``MI_FITNESS_USER_ID`` / ``MI_FITNESS_PASS_TOKEN``
    （``.env.example`` 里一直写着、但过去没有任何代码读取的两个变量）真正生效。
    keyring 优先，因为 ``setup`` 命令写入的是它，用户手改环境变量不会覆盖已保存的值。
    """
    user_id: str | None = None
    pass_token: str | None = None

    try:
        user_id = keyring.get_password(SERVICE_NAME, f"{ACCOUNT_NAME}_user_id")
        pass_token = keyring.get_password(SERVICE_NAME, f"{ACCOUNT_NAME}_pass_token")
    except Exception as exc:
        # 无 keyring 后端是常见情况（headless），降级到环境变量而不是直接失败
        logger.debug("Keyring unavailable, falling back to environment: %s", exc)

    user_id = user_id or os.environ.get(ENV_USER_ID) or None
    pass_token = pass_token or os.environ.get(ENV_PASS_TOKEN) or None
    return user_id, pass_token


def delete_mi_fitness_token() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, f"{ACCOUNT_NAME}_user_id")
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception as exc:
        logger.error("Failed to delete Mi Fitness user_id: %s", exc)
    try:
        keyring.delete_password(SERVICE_NAME, f"{ACCOUNT_NAME}_pass_token")
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception as exc:
        logger.error("Failed to delete Mi Fitness passToken: %s", exc)
