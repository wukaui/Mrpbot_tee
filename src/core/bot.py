# Mrpbot Bot Class
"""
机器人主类 - Mrpbot

负责：
- 初始化和配置
- 组件管理
- 状态监控
"""

import logging
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from .engine import MessageEngine
    from .lifecycle import LifecycleManager

logger = logging.getLogger(__name__)


class Mrpbot:
    """
    
    Attributes:
        config: 配置字典
        name: 机器人名称
        is_running: 运行状态
        start_time: 启动时间
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化机器人
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.name = config.get('bot', {}).get('name', '智能助手')
        self.identity_file = config.get('bot', {}).get('identity_file', 'config/identity.md')
        
        # 状态
        self.is_running = False
        self.start_time: Optional[datetime] = None
        
        # 组件
        self.engine: Optional[MessageEngine] = None
        self.channels: Dict[str, Any] = {}
        self.features: Dict[str, Any] = {}
        self.lifecycle: Optional[LifecycleManager] = None
        
        logger.info(f"{self.name} 初始化完成")
    
    async def start(self):
        """
        启动机器人
        
        按顺序初始化：
        1. 引擎
        2. 渠道
        3. 功能
        4. 生命周期管理
        """
        try:
            logger.info("=" * 50)
            logger.info(f"{self.name} 正在启动...")
            logger.info("=" * 50)
            
            self.is_running = True
            self.start_time = datetime.now()
            
            # 1. 初始化渠道（先于引擎，因为引擎需要渠道引用）
            logger.info("初始化通信渠道...")
            await self._init_channels()
            logger.info(f"✓ 已加载 {len(self.channels)} 个渠道")
            
            # 2. 初始化引擎
            logger.info("初始化消息引擎...")
            from .engine import MessageEngine
            self.engine = MessageEngine(self.config, self.channels)
            await self.engine.initialize()
            logger.info("✓ 消息引擎已就绪")
            
            # 设置渠道的 engine 引用（引擎已创建）
            for channel in self.channels.values():
                if hasattr(channel, 'engine'):
                    channel.engine = self.engine
            logger.info("✓ 渠道已关联引擎")
            
            # 3. 初始化功能
            logger.info("初始化功能模块...")
            await self._init_features()
            logger.info(f"✓ 已加载 {len(self.features)} 个功能")
            
            # 4. 初始化生命周期管理
            logger.info("初始化生命周期管理...")
            from .lifecycle import LifecycleManager
            self.lifecycle = LifecycleManager()
            await self.lifecycle.start(self)
            logger.info("✓ 生命周期管理已就绪")
            
            logger.info("=" * 50)
            logger.info(f"{self.name} 启动完成！")
            logger.info("=" * 50)
            
        except Exception as e:
            logger.error(f"启动失败：{e}", exc_info=True)
            self.is_running = False
            raise
    
    async def stop(self):
        """
        停止机器人
        
        按顺序关闭：
        1. 生命周期管理
        2. 功能
        3. 渠道
        4. 引擎
        """
        try:
            logger.info("=" * 50)
            logger.info(f"{self.name} 正在停止...")
            logger.info("=" * 50)
            
            self.is_running = False
            
            # 1. 停止生命周期管理
            if self.lifecycle:
                logger.info("停止生命周期管理...")
                await self.lifecycle.stop(self)
                logger.info("✓ 生命周期管理已停止")
            
            # 2. 停止功能
            logger.info("停止功能模块...")
            for name, feature in self.features.items():
                if hasattr(feature, 'shutdown'):
                    await feature.shutdown()
            logger.info("✓ 功能模块已停止")
            
            # 3. 停止渠道
            logger.info("停止通信渠道...")
            for name, channel in self.channels.items():
                if hasattr(channel, 'stop'):
                    await channel.stop()
            logger.info("✓ 通信渠道已停止")
            
            # 4. 停止引擎
            if self.engine:
                logger.info("停止消息引擎...")
                await self.engine.shutdown()
                logger.info("✓ 消息引擎已停止")
            
            logger.info("=" * 50)
            logger.info(f"{self.name} 已停止")
            logger.info("=" * 50)
            
        except Exception as e:
            logger.error(f"停止时出错：{e}", exc_info=True)
    
    async def _init_channels(self):
        """初始化通信渠道"""
        from src.channels import OneBotChannel
        
        # OneBot 渠道
        if self.config.get('channels', {}).get('onebot', {}).get('enabled', False):
            try:
                # 先创建渠道，不传 engine（engine 还没创建）
                channel = OneBotChannel(self.config, None)
                await channel.start()
                self.channels['onebot'] = channel
                logger.info("✓ OneBot 渠道已启动")
            except Exception as e:
                logger.error(f"OneBot 渠道启动失败：{e}")
    
    async def _init_features(self):
        """初始化功能模块"""
        from src.features import load_all_features
        
        try:
            self.features = await load_all_features(self.config, self.engine)
        except Exception as e:
            logger.error(f"功能模块加载失败：{e}")
            self.features = {}
    
    async def handle_message(self, message: Dict[str, Any]):
        """
        处理消息入口
        
        Args:
            message: 消息字典
        """
        if not self.is_running:
            logger.warning("机器人未运行，跳过消息处理")
            return
        
        if not self.engine:
            logger.warning("引擎未初始化，跳过消息处理")
            return
        
        try:
            await self.engine.process_message(message)
        except Exception as e:
            logger.error(f"消息处理失败：{e}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取机器人状态
        
        Returns:
            状态字典
        """
        from datetime import timedelta
        
        uptime = timedelta()
        if self.start_time:
            uptime = datetime.now() - self.start_time
        
        return {
            'name': self.name,
            'version': '2.0.0',
            'is_running': self.is_running,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'uptime_seconds': uptime.total_seconds(),
            'uptime_human': str(uptime),
            'channels': list(self.channels.keys()),
            'features': list(self.features.keys()),
        }
