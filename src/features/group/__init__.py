# Group Feature
"""
群聊功能模块
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class GroupFeature:
    """群聊功能模块"""
    
    def __init__(self, config: Dict[str, Any], engine):
        self.config = config
        self.engine = engine
        self.name = "group"
        self.is_initialized = False
        
        self.reply_threshold = config.get('features', {}).get('group', {}).get('reply_threshold', 45)
        self.cooldown = config.get('features', {}).get('group', {}).get('cooldown', 60)
    
    async def initialize(self):
        """初始化"""
        logger.info(f"✓ 群聊功能已初始化 (阈值:{self.reply_threshold}, 冷却:{self.cooldown}s)")
        self.is_initialized = True
    
    async def shutdown(self):
        """关闭"""
        logger.info("群聊功能已关闭")
        self.is_initialized = False
