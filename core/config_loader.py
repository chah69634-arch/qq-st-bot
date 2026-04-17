"""
配置加载模块
全局单例，读取 config.yaml，供所有模块使用
"""

import yaml
from pathlib import Path

_config: dict | None = None
_CONFIG_PATH = Path("config.yaml")


def get_config() -> dict:
    """
    返回配置字典（单例）
    第一次调用时从 config.yaml 加载，之后直接返回缓存
    """
    global _config
    if _config is None:
        reload_config()
    return _config


def reload_config() -> dict:
    """重新从磁盘读取 config.yaml（admin 修改后调用）"""
    global _config
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise RuntimeError(f"配置文件不存在：{_CONFIG_PATH.absolute()}")
    except yaml.YAMLError as e:
        raise RuntimeError(f"配置文件格式错误：{e}")
    return _config
