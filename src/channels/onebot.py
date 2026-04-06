# OneBot Channel
"""
OneBot 协议渠道

负责：
- WebSocket 连接
- 消息收发
- 自动重连
"""

import logging
import asyncio
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class OneBotChannel:
    """
    OneBot 通信渠道
    
    Attributes:
        config: 配置字典
        engine: 消息引擎
        ws_url: WebSocket 地址
        is_running: 运行状态
    """
    
    def __init__(self, config: Dict[str, Any], engine):
        """
        初始化 OneBot 渠道
        
        Args:
            config: 配置字典
            engine: 消息引擎
        """
        self.config = config
        self.engine = engine
        self.ws_url = config.get('channels', {}).get('onebot', {}).get('ws_url', 'ws://127.0.0.1:6199')
        self.access_token = config.get('channels', {}).get('onebot', {}).get('access_token', '')
        
        self.websocket: Optional[Any] = None
        self.is_running = False
        self.reconnect_count = 0
        self._message_tasks: set[asyncio.Task] = set()
    
    async def start(self):
        """启动渠道"""
        logger.info(f"启动 OneBot 渠道：{self.ws_url}")
        self.is_running = True
        
        # 启动连接循环
        asyncio.create_task(self._connect_loop())
    
    async def stop(self):
        """停止渠道"""
        logger.info("停止 OneBot 渠道")
        self.is_running = False

        # 取消仍在执行的消息任务，避免停机时残留处理协程
        for task in list(self._message_tasks):
            task.cancel()
        if self._message_tasks:
            await asyncio.gather(*self._message_tasks, return_exceptions=True)
        self._message_tasks.clear()
        
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.error(f"关闭 WebSocket 失败：{e}")
    
    async def _connect_loop(self):
        """连接循环"""
        reconnect_interval = self.config.get('channels', {}).get('onebot', {}).get('reconnect_interval', 5)
        
        while self.is_running:
            try:
                await self._connect()
            except Exception as e:
                self.reconnect_count += 1
                logger.error(f"OneBot 连接失败 (第{self.reconnect_count}次): {e}")
                
                if self.is_running:
                    logger.info(f"{reconnect_interval}秒后重试...")
                    await asyncio.sleep(reconnect_interval)
    
    async def _connect(self):
        """建立 WebSocket 连接"""
        import websockets
        
        headers = {}
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        
        try:
            # websockets 16.0+ 使用 additional_headers 参数
            logger.info(f"正在连接 OneBot: {self.ws_url}")
            async with websockets.connect(self.ws_url, additional_headers=headers) as ws:
                self.websocket = ws
                self.reconnect_count = 0
                logger.info("✓ OneBot 连接成功")
                
                while self.is_running:
                    try:
                        message = await ws.recv()
                        # 高频消息日志降为 debug，避免日志膨胀
                        try:
                            msg_data = json.loads(message)
                            logger.debug(
                                "收到消息: post_type=%s, user_id=%s, group_id=%s, message_type=%s",
                                msg_data.get('post_type', 'unknown'),
                                msg_data.get('user_id'),
                                msg_data.get('group_id'),
                                msg_data.get('message_type'),
                            )
                        except Exception:
                            logger.debug("收到非 JSON 消息片段：%s...", message[:120])
                        await self._handle_message(message)
                    except websockets.ConnectionClosed:
                        logger.warning("⚠️ OneBot 连接断开")
                        break
                    except Exception as e:
                        logger.error(f"消息处理错误：{e}", exc_info=True)
                        
        except Exception as e:
            raise e
    
    async def _handle_message(self, message: str):
        """
        处理收到的消息
        
        Args:
            message: 原始消息
        """
        try:
            data = json.loads(message)
            
            # 忽略元事件
            if data.get('post_type') == 'meta_event':
                return
            
            # 处理消息
            if data.get('post_type') == 'message':
                # 忽略机器人自己发出的回显消息，避免自触发
                if str(data.get('user_id')) == str(data.get('self_id')):
                    return
                task = asyncio.create_task(self.engine.process_message(data))
                self._message_tasks.add(task)
                task.add_done_callback(self._on_message_task_done)
                
        except json.JSONDecodeError:
            logger.error(f"无效 JSON: {message}")
        except Exception as e:
            logger.error(f"消息处理失败：{e}", exc_info=True)

    def _on_message_task_done(self, task: asyncio.Task):
        """回收消息任务并记录异常。"""
        self._message_tasks.discard(task)
        if task.cancelled():
            return

        exc = task.exception()
        if exc is not None:
            logger.error(f"异步消息任务失败：{exc}", exc_info=True)
    
    async def send_message(self, message_type: str, target_id: int, content: str):
        """
        发送消息
        
        Args:
            message_type: 消息类型 (private/group)
            target_id: 目标 ID
            content: 消息内容
        """
        if not self.websocket:
            logger.warning("OneBot 未连接，无法发送消息")
            return
        
        payload = {
            'action': 'send_msg',
            'params': {
                'message_type': message_type,
                'user_id' if message_type == 'private' else 'group_id': target_id,
                'message': content,
            }
        }
        
        try:
            await self.websocket.send(json.dumps(payload))
            logger.debug(f"消息已发送：{message_type} {target_id}")
        except Exception as e:
            logger.error(f"发送消息失败：{e}")
