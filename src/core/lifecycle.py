# Lifecycle Manager
"""
生命周期管理器

负责：
- 启动和停止流程
- 心跳任务
- 自动保存
- 状态监控
"""

import logging
import asyncio
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class LifecycleManager:
    """
    生命周期管理器
    
    Attributes:
        start_time: 启动时间
        stop_time: 停止时间
        tasks: 后台任务列表
    """
    
    def __init__(self):
        """初始化生命周期管理器"""
        self.start_time: Optional[datetime] = None
        self.stop_time: Optional[datetime] = None
        self.tasks: List[asyncio.Task] = []
    
    async def start(self, bot):
        """
        启动生命周期管理
        
        Args:
            bot: 机器人实例
        """
        try:
            logger.info("启动生命周期管理...")
            
            self.start_time = datetime.now()
            logger.info(f"生命周期管理启动于 {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 启动心跳任务
            heartbeat_task = asyncio.create_task(self._heartbeat(bot))
            self.tasks.append(heartbeat_task)
            logger.info("✓ 心跳任务已启动")
            
            # 启动记忆保存任务
            memory_save_task = asyncio.create_task(self._auto_save_memory(bot))
            self.tasks.append(memory_save_task)
            logger.info("✓ 记忆保存任务已启动")
            
            # 启动状态检查任务
            status_check_task = asyncio.create_task(self._status_check(bot))
            self.tasks.append(status_check_task)
            logger.info("✓ 状态检查任务已启动")
            
            logger.info("✓ 生命周期管理已启动")
            
        except Exception as e:
            logger.error(f"生命周期管理启动失败：{e}", exc_info=True)
            raise
    
    async def stop(self, bot):
        """
        停止生命周期管理
        
        Args:
            bot: 机器人实例
        """
        try:
            logger.info("停止生命周期管理...")
            
            self.stop_time = datetime.now()
            logger.info(f"生命周期管理停止于 {self.stop_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 取消所有任务
            logger.info(f"正在取消 {len(self.tasks)} 个任务...")
            for task in self.tasks:
                task.cancel()
            
            # 等待任务结束
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
                logger.info("✓ 所有任务已停止")
            
            self.tasks.clear()
            logger.info("✓ 生命周期管理已停止")
            
        except Exception as e:
            logger.error(f"生命周期管理停止失败：{e}", exc_info=True)
    
    async def _heartbeat(self, bot):
        """
        心跳任务
        
        Args:
            bot: 机器人实例
        """
        logger.info("心跳任务已启动")
        
        while bot.is_running:
            try:
                await asyncio.sleep(60)  # 每分钟
                
                if bot.is_running:
                    status = bot.get_status()
                    logger.debug(
                        f"❤️ 心跳 | {status['name']} | "
                        f"运行 {status['uptime_human']} | "
                        f"渠道 {len(status['channels'])} | "
                        f"功能 {len(status['features'])}"
                    )
                    
            except asyncio.CancelledError:
                logger.info("心跳任务已取消")
                break
            except Exception as e:
                logger.error(f"心跳任务错误：{e}")
    
    async def _auto_save_memory(self, bot):
        """
        自动保存记忆
        
        Args:
            bot: 机器人实例
        """
        logger.info("记忆保存任务已启动")
        
        while bot.is_running:
            try:
                await asyncio.sleep(300)  # 每 5 分钟
                
                if bot.is_running and bot.engine and bot.engine.memory_system:
                    try:
                        await bot.engine.memory_system.save_all()
                        logger.debug("✓ 记忆已自动保存")
                    except Exception as e:
                        logger.error(f"记忆保存失败：{e}")
                        
            except asyncio.CancelledError:
                logger.info("记忆保存任务已取消")
                break
            except Exception as e:
                logger.error(f"记忆保存任务错误：{e}")
    
    async def _status_check(self, bot):
        """
        状态检查任务
        
        Args:
            bot: 机器人实例
        """
        logger.info("状态检查任务已启动")
        
        while bot.is_running:
            try:
                await asyncio.sleep(600)  # 每 10 分钟
                
                if bot.is_running:
                    # 检查 LLM 连接
                    if bot.engine and bot.engine.llm_client:
                        if not bot.engine.llm_client.is_initialized:
                            logger.warning("⚠️ LLM 客户端未初始化")
                    
                    # 检查渠道连接
                    for name, channel in bot.channels.items():
                        if not channel.is_running:
                            logger.warning(f"⚠️ 渠道 {name} 未运行")
                    
                    logger.debug("✓ 状态检查完成")
                    
            except asyncio.CancelledError:
                logger.info("状态检查任务已取消")
                break
            except Exception as e:
                logger.error(f"状态检查任务错误：{e}")
    
    def get_uptime(self) -> float:
        """
        获取运行时间（秒）
        
        Returns:
            运行时间
        """
        if not self.start_time:
            return 0.0
        
        end_time = self.stop_time or datetime.now()
        return (end_time - self.start_time).total_seconds()
