# Proactive Feature
"""
主动消息功能模块
"""

import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ProactiveFeature:
    """主动消息功能模块"""
    
    def __init__(self, config: Dict[str, Any], engine):
        self.config = config
        self.engine = engine
        self.name = "proactive"
        self.is_initialized = False
        self.is_running = False
    
    async def initialize(self):
        """初始化"""
        logger.info("✓ 主动消息功能已初始化")
        self.is_initialized = True
        self.is_running = True
        
        # 启动主动消息任务
        asyncio.create_task(self._proactive_loop())
    
    async def shutdown(self):
        """关闭"""
        logger.info("主动消息功能已关闭")
        self.is_running = False
        self.is_initialized = False
    
    async def _proactive_loop(self):
        """主动消息循环"""
        check_interval = self.config.get('features', {}).get('proactive', {}).get('check_interval', 3600)
        
        while self.is_running:
            try:
                await asyncio.sleep(check_interval)
                
                # 主动消息逻辑
                logger.debug("主动消息检查")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主动消息错误：{e}")
