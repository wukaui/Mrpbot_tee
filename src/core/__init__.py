# Mrpbot Core Package
"""
Mrpbot 2.0 核心模块

提供机器人核心功能：
- Mrpbot: 机器人主类
- MessageEngine: 消息处理引擎
- LifecycleManager: 生命周期管理
"""

from .bot import Mrpbot
from .engine import MessageEngine
from .lifecycle import LifecycleManager
from .meta_judge import MetaJudge

__version__ = "2.0.0"
__all__ = ['Mrpbot', 'MessageEngine', 'LifecycleManager', 'MetaJudge']
