# Features Package
"""
功能模块包

包含：
- Chat: 聊天功能（核心）
- Group: 群聊策略
- Memory: 记忆系统（核心）
- Proactive: 主动消息
"""

from .chat import ChatFeature
from .group import GroupFeature
from .memory import MemoryFeature
from .proactive import ProactiveFeature

__all__ = [
    'ChatFeature',
    'GroupFeature',
    'MemoryFeature',
    'ProactiveFeature',
]


async def load_all_features(config, engine):
    """
    加载所有功能模块
    
    Args:
        config: 配置字典
        engine: 消息引擎
        
    Returns:
        功能模块字典
    """
    features = {}
    
    try:
        # 聊天功能
        if config.get('features', {}).get('chat', {}).get('enabled', True):
            features['chat'] = ChatFeature(config, engine)
            await features['chat'].initialize()
    except Exception as e:
        logger.error(f"聊天功能加载失败：{e}")
    
    try:
        # 群聊功能
        if config.get('features', {}).get('group', {}).get('enabled', True):
            features['group'] = GroupFeature(config, engine)
            await features['group'].initialize()
    except Exception as e:
        logger.error(f"群聊功能加载失败：{e}")
    
    try:
        # 记忆功能
        if config.get('features', {}).get('memory', {}).get('enabled', True):
            features['memory'] = MemoryFeature(config, engine)
            await features['memory'].initialize()
    except Exception as e:
        logger.error(f"记忆功能加载失败：{e}")
    
    try:
        # 主动消息
        if config.get('features', {}).get('proactive', {}).get('enabled', True):
            features['proactive'] = ProactiveFeature(config, engine)
            await features['proactive'].initialize()
    except Exception as e:
        logger.error(f"主动消息加载失败：{e}")
    
    return features
