# Config Loader
"""
配置加载
"""

import os
import yaml
from typing import Dict, Any, Optional

import logging
logger = logging.getLogger(__name__)


def load_config(config_file: str = 'config/bot.yaml') -> Dict[str, Any]:
    """
    加载配置文件
    
    Args:
        config_file: 配置文件路径
        
    Returns:
        配置字典
    """
    
    # 检查文件存在
    if not os.path.exists(config_file):
        # 尝试加载示例配置
        example_file = config_file + '.example'
        if os.path.exists(example_file):
            logger.warning(f"配置文件不存在，使用示例配置：{example_file}")
            config_file = example_file
        else:
            logger.error(f"配置文件不存在：{config_file}")
            return {}
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # 环境变量替换
        config = _replace_env_vars(config)
        
        logger.info(f"✓ 配置已加载：{config_file}")
        return config
        
    except Exception as e:
        logger.error(f"加载配置失败：{e}", exc_info=True)
        return {}


def _replace_env_vars(obj):
    """
    替换环境变量
    
    Args:
        obj: 对象
        
    Returns:
        替换后的对象
    """
    if isinstance(obj, dict):
        return {k: _replace_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_replace_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        if obj.startswith('${') and obj.endswith('}'):
            env_var = obj[2:-1]
            value = os.getenv(env_var)
            if value is None:
                logger.warning(f"环境变量未设置：{env_var}")
                return obj
            return value
        return obj
    else:
        return obj
