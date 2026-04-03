# Message Engine
"""
消息引擎 - 处理消息的核心逻辑

负责：
- 消息解析和验证
- 回复决策
- LLM 调用
- 记忆更新
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MessageEngine:
    """
    消息处理引擎
    
    Attributes:
        config: 配置字典
        is_initialized: 初始化状态
        reply_desire: 回复欲望字典
        cooldowns: 冷却时间字典
    """
    
    def __init__(self, config: Dict[str, Any], channels: Optional[Dict[str, Any]] = None):
        """
        初始化引擎
        
        Args:
            config: 配置字典
            channels: 渠道字典（用于发送消息）
        """
        self.config = config
        self.channels = channels or {}
        self.is_initialized = False
        
        # 消息队列
        self.message_queue: List[Dict[str, Any]] = []
        
        # 回复欲望系统
        self.reply_desire: Dict[str, float] = {}
        self.cooldowns: Dict[str, datetime] = {}
        
        # 系统引用
        self.memory_system: Optional[Any] = None
        self.llm_client: Optional[Any] = None
    
    async def initialize(self):
        """
        初始化引擎
        
        按顺序初始化：
        1. LLM 客户端
        2. 记忆系统
        """
        try:
            logger.info("正在初始化消息引擎...")
            
            # 1. 初始化 LLM
            logger.info("初始化 LLM 客户端...")
            from src.llm import LLMClient
            self.llm_client = LLMClient(self.config)
            await self.llm_client.initialize()
            
            # 2. 初始化记忆系统
            logger.info("初始化记忆系统...")
            from src.features.memory import MemorySystem
            self.memory_system = MemorySystem(self.config)
            await self.memory_system.initialize()
            
            self.is_initialized = True
            logger.info("✓ 消息引擎初始化完成")
            
        except Exception as e:
            logger.error(f"引擎初始化失败：{e}", exc_info=True)
            raise
    
    async def shutdown(self):
        """
        关闭引擎
        
        按顺序关闭：
        1. 记忆系统
        2. LLM 客户端
        """
        try:
            logger.info("正在关闭消息引擎...")
            
            # 1. 保存记忆
            if self.memory_system:
                logger.info("保存记忆...")
                await self.memory_system.save_all()
                logger.info("✓ 记忆已保存")
            
            # 2. 关闭 LLM
            if self.llm_client:
                logger.info("关闭 LLM 客户端...")
                await self.llm_client.close()
                logger.info("✓ LLM 客户端已关闭")
            
            self.is_initialized = False
            logger.info("✓ 消息引擎已关闭")
            
        except Exception as e:
            logger.error(f"引擎关闭失败：{e}", exc_info=True)
    
    async def process_message(self, message: Dict[str, Any]):
        """
        处理单条消息
        
        Args:
            message: 消息字典
        """
        if not self.is_initialized:
            logger.warning("引擎未初始化，跳过消息处理")
            return
        
        try:
            # 提取消息信息
            user_id = str(message.get('user_id', 'unknown'))
            group_id = message.get('group_id')
            content = self._extract_text(message.get('message', ''))
            message_type = message.get('message_type', 'private')
            
            # 验证消息
            if not self._validate_message(message):
                logger.warning("⚠️ 无效消息，跳过")
                return
            
            # 更新记忆
            if self.memory_system:
                await self.memory_system.add_message(user_id, group_id, message)
            
            # 更新回复欲望
            raw_message = message.get('raw_message', '')
            self._update_reply_desire(user_id, group_id, content, raw_message, message)
            
            # 检查是否应该回复
            should_reply = await self._should_reply(user_id, group_id, content, raw_message)
            
            if should_reply:
                logger.info(f"✓ 回复 {user_id[-4:]}: {content[:50]}...")
                # 生成回复
                response = await self._generate_response(message)
                
                # 发送回复
                if response:
                    await self._send_response(response, message)
                    # 仅在实际发送回复后进入冷却
                    self._update_cooldown(user_id, group_id)
            else:
                logger.debug(f"跳过回复 {user_id[-4:]}")
            
        except Exception as e:
            logger.error(f"消息处理失败：{e}", exc_info=True)

    def _extract_text(self, content: Any) -> str:
        """
        将 OneBot 消息字段统一转换为纯文本。

        Args:
            content: message 字段（str / list / 其他）

        Returns:
            纯文本消息
        """
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: List[str] = []
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':
                    text_parts.append(part.get('data', {}).get('text', ''))
                elif isinstance(part, str):
                    text_parts.append(part)
            return ''.join(text_parts)

        return str(content or '')
    
    def _validate_message(self, message: Dict[str, Any]) -> bool:
        """
        验证消息
        
        Args:
            message: 消息字典
            
        Returns:
            是否有效
        """
        # 必须有 user_id
        if 'user_id' not in message:
            logger.warning("❌ 缺少 user_id")
            return False
        
        # 必须有 message
        if 'message' not in message:
            logger.warning("❌ 缺少 message")
            return False
        
        # 消息不能为空
        content = self._extract_text(message.get('message', ''))
        logger.debug(f"消息内容类型：{type(content)}, 内容：{str(content)[:100]}...")
        
        if not content or not content.strip():
            logger.warning("❌ 消息内容为空")
            return False
        
        logger.debug(f"✓ 消息验证通过：{content[:50]}...")
        return True
    
    def _update_reply_desire(self, user_id: str, group_id: Optional[int], content: str, raw_message: Optional[str] = None, message: Optional[Dict] = None):
        """
        更新回复欲望
        
        Args:
            user_id: 用户 ID
            group_id: 群聊 ID
            content: 消息内容（转换后的文本）
            raw_message: 原始消息（包含 CQ 码）
            message: 完整消息字典
        """
        message = message or {}
        key = f"group_{group_id}" if group_id else f"user_{user_id}"
        
        # 获取当前欲望值
        current = self.reply_desire.get(key, 0.0)
        
        # @机器人 增加欲望（检查 CQ 码或文本@）
        is_mentioned = False
        
        # 检查 CQ 码格式的@
        if raw_message:
            import re
            cq_at_pattern = r'\[CQ:at,qq=(\d+)\]'
            matches = re.findall(cq_at_pattern, raw_message)
            self_qq = str(message.get('self_id', '0'))
            if self_qq in matches:
                is_mentioned = True
        
        # 检查文本@
        if '@' in content:
            is_mentioned = True
        
        # 检查是否叫了机器人名字
        bot_names = ['三月七', '三月', '小三月', '77', '七七']
        if any(name in content for name in bot_names):
            is_mentioned = True
        
        if is_mentioned:
            current += 20.0
            logger.debug(f"{user_id[-4:]} 被@，欲望 +20")
        
        # 有趣内容增加欲望
        interesting_words = ['哈哈', '笑死', '好玩', '有趣', '嘿嘿', '233']
        if any(word in content for word in interesting_words):
            current += 10.0
            logger.debug(f"{user_id[-4:]} 有趣内容，欲望 +10")
        
        # 问题增加欲望
        question_chars = ['?', '？', '吗', '呢', '什么', '怎么', '为什么']
        if any(char in content for char in question_chars):
            current += 15.0
            logger.debug(f"{user_id[-4:]} 提问，欲望 +15")
        
        # 限制最大值
        current = min(100.0, current)
        
        # 时间衰减
        decay_rate = self.config.get('features', {}).get('group', {}).get('decay_rate', 0.1)
        current = max(0.0, current - decay_rate)
        
        self.reply_desire[key] = current
    
    async def _should_reply(self, user_id: str, group_id: Optional[int], content: str, raw_message: Optional[str] = None) -> bool:
        """
        判断是否应该回复（结合规则 + LLM 智能评分 + 群聊上下文）
        
        Args:
            user_id: 用户 ID
            group_id: 群聊 ID
            content: 消息内容
            raw_message: 原始消息（包含 CQ 码）
            
        Returns:
            是否回复
        """
        # 私聊必回
        if not group_id:
            return True
        
        # @机器人必回
        is_mentioned = False
        if raw_message and f'[CQ:at,qq=' in raw_message:
            is_mentioned = True
        if '@' in content:
            is_mentioned = True
        
        if is_mentioned:
            reply_when_mentioned = self.config.get('features', {}).get('group', {}).get('reply_when_mentioned', True)
            if reply_when_mentioned:
                logger.debug(f"{user_id[-4:]} @机器人，必回")
                return True
        
        # 叫机器人名字必回
        bot_names = ['三月七', '三月', '小三月', '77', '七七']
        if any(name in content for name in bot_names):
            logger.debug(f"{user_id[-4:]} 叫机器人名字，必回")
            return True

        # 冷却期间不回复（必回场景已在上面提前返回）
        if self._is_in_cooldown(user_id, group_id):
            logger.debug(f"{user_id[-4:]} 在冷却中，跳过回复")
            return False
        
        # LLM 智能评分
        llm_score = await self._llm_reply_score(content, user_id, group_id)
        
        # 结合欲望值决策
        key = f"group_{group_id}" if group_id else f"user_{user_id}"
        desire = self.reply_desire.get(key, 0.0)
        threshold = self.config.get('features', {}).get('group', {}).get('reply_threshold', 45)
        
        if llm_score >= 80:
            logger.debug(f"{user_id[-4:]} LLM {llm_score:.0f}>=80，必回")
            return True
        
        if llm_score >= 60 and desire >= threshold:
            logger.debug(f"{user_id[-4:]} LLM {llm_score:.0f}>=60，欲望 {desire:.0f}>=阈值，回复")
            return True
        
        if llm_score >= 40 and desire >= (threshold + 10):
            logger.debug(f"{user_id[-4:]} LLM {llm_score:.0f}>=40，欲望 {desire:.0f}>=高阈值，回复")
            return True
        
        logger.debug(f"{user_id[-4:]} LLM {llm_score:.0f}，欲望 {desire:.0f}，不回")
        return False
    
    async def _llm_reply_score(self, content: str, user_id: str, group_id: Optional[int]) -> float:
        """
        让 LLM 判断消息是否需要回复，返回评分（0-100）
        考虑群聊上下文，理解多人对话场景
        
        Args:
            content: 消息内容
            user_id: 用户 ID
            group_id: 群聊 ID（用于获取群聊上下文）
            
        Returns:
            评分（0-100）
        """
        if not self.llm_client or not self.is_initialized:
            return 50.0
        
        try:
            # 构建群聊上下文
            group_context = ""
            if group_id and self.memory_system:
                try:
                    recent_messages = await self.memory_system.get_group_recent(group_id, limit=10)
                    if recent_messages:
                        context_lines = []
                        for msg in recent_messages:
                            sender_id = msg.get('user_id', 'unknown')
                            message_payload = msg.get('message', {})
                            if isinstance(message_payload, dict):
                                msg_content = self._extract_text(message_payload.get('message', ''))
                            else:
                                msg_content = self._extract_text(message_payload)
                            context_lines.append(f"用户{sender_id[-4:]}: {msg_content[:50]}")
                        group_context = "\n".join(context_lines)
                except Exception as e:
                    logger.error(f"获取群聊上下文失败：{e}")
            
            # 构建提示词
            system_prompt = """你是 QQ 群聊助手，判断消息是否需要回复。

评分标准（0-100）：
- 80-100：提问、@、求助、对话邀请
- 60-79：分享、感慨、有趣内容
- 40-59：日常聊天、陈述句
- 20-39：重复、无意义
- 0-19：广告、刷屏

只返回数字（0-100）。"""
            
            if group_context:
                user_prompt = f"""【群聊上下文】
{group_context}

【当前消息】
{content[:200]}

评分（0-100）："""
            else:
                user_prompt = f"消息：{content[:200]}\n\n评分（0-100）："
            
            # 调用 LLM
            import openai
            if not hasattr(self.llm_client, 'client') or not self.llm_client.client:
                return 50.0
            
            response = await self.llm_client.client.chat.completions.create(
                model=self.llm_client.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                max_tokens=5,
                temperature=0.3,
            )
            
            # 解析评分
            score_text = response.choices[0].message.content.strip()
            import re
            match = re.search(r'\d+', score_text)
            if match:
                score = float(match.group())
                return max(0.0, min(100.0, score))
            else:
                return 50.0
                
        except Exception as e:
            logger.error(f"LLM 评分失败：{e}")
            return 50.0
    
    def _update_cooldown(self, user_id: str, group_id: Optional[int]):
        """
        更新冷却时间
        
        Args:
            user_id: 用户 ID
            group_id: 群聊 ID
        """
        key = f"group_{group_id}" if group_id else f"user_{user_id}"
        cooldown_seconds = self.config.get('features', {}).get('group', {}).get('cooldown', 60)
        
        self.cooldowns[key] = datetime.now() + timedelta(seconds=cooldown_seconds)
        logger.debug(f"用户 {key} 冷却时间更新为 {cooldown_seconds}秒")

    def _is_in_cooldown(self, user_id: str, group_id: Optional[int]) -> bool:
        """
        判断当前会话是否处于冷却期。

        Args:
            user_id: 用户 ID
            group_id: 群聊 ID

        Returns:
            是否在冷却中
        """
        key = f"group_{group_id}" if group_id else f"user_{user_id}"
        cooldown_until = self.cooldowns.get(key)
        if not cooldown_until:
            return False
        return datetime.now() < cooldown_until
    
    async def _generate_response(self, message: Dict[str, Any]) -> Optional[str]:
        """
        生成回复
        
        Args:
            message: 消息字典
            
        Returns:
            回复内容
        """
        if not self.llm_client:
            logger.warning("LLM 客户端未初始化")
            return None
        
        try:
            # 获取上下文
            context = await self._build_context(message)
            
            # 提取纯文本消息
            content = self._extract_text(message.get('message', ''))
            
            # 调用 LLM
            response = await self.llm_client.chat(content, context)
            
            return response
            
        except Exception as e:
            logger.error(f"生成回复失败：{e}", exc_info=True)
            return None
    
    async def _build_context(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建上下文
        
        Args:
            message: 消息字典
            
        Returns:
            上下文字典
        """
        user_id = str(message.get('user_id', 'unknown'))
        group_id = message.get('group_id')
        
        context = {
            'user_id': user_id,
            'group_id': group_id,
            'recent_messages': [],
            'group_profile': {},
        }
        
        # 获取最近消息
        if self.memory_system:
            try:
                if group_id:
                    context['recent_messages'] = await self.memory_system.get_group_recent(group_id, limit=12)
                    context['group_profile'] = await self.memory_system.get_group_profile(group_id, limit=50)
                else:
                    context['recent_messages'] = await self.memory_system.get_recent(user_id, group_id, limit=8)
            except Exception as e:
                logger.error(f"获取最近消息失败：{e}")
        
        return context
    
    async def _send_response(self, response: str, original_message: Dict[str, Any]):
        """
        发送回复
        
        Args:
            response: 回复内容
            original_message: 原始消息
        """
        try:
            logger.info(f"准备发送回复：{response[:50]}...")
            
            # 通过 OneBot 渠道发送
            if 'onebot' in self.channels:
                message_type = 'group' if original_message.get('group_id') else 'private'
                target_id = original_message.get('group_id') or original_message.get('user_id')
                
                await self.channels['onebot'].send_message(message_type, target_id, response)
                logger.info(f"✓ 回复已发送到 {message_type} {target_id}")

                # 将机器人回复也写入记忆，帮助模型区分 user/assistant 并理解群聊脉络
                if self.memory_system:
                    group_id = original_message.get('group_id')
                    bot_id = str(original_message.get('self_id', 'bot'))
                    bot_name = self.config.get('bot', {}).get('name', 'bot')
                    await self.memory_system.add_bot_message(group_id, response, bot_id=bot_id, bot_name=bot_name)
            else:
                logger.warning("⚠️ OneBot 渠道未启用，仅记录日志")
                logger.info(f"回复：{response}")
            
        except Exception as e:
            logger.error(f"发送回复失败：{e}", exc_info=True)
