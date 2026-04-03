# Channels Package
"""
通信渠道模块

支持：
- OneBot (QQ)
- 微信 (计划)
- Telegram (计划)
"""

from .onebot import OneBotChannel

__all__ = ['OneBotChannel']
