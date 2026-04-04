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
from collections import deque
import asyncio
import random
from difflib import SequenceMatcher

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
        self.desire_state: Dict[str, Dict[str, Any]] = {}
        self.conversation_state: Dict[str, Dict[str, Any]] = {}
        self.group_quiet_until: Dict[str, datetime] = {}
        self.decision_trace: Dict[str, Dict[str, Any]] = {}
        
        # 系统引用
        self.memory_system: Optional[Any] = None
        self.llm_client: Optional[Any] = None
        self.meta_judge: Optional[Any] = None
    
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

            # 3. 初始化元 AI 裁决器
            from .meta_judge import MetaJudge
            self.meta_judge = MetaJudge(self.config, self.llm_client)
            
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
            conv_key = f"group_{group_id}" if group_id else f"user_{user_id}"
            raw_message = message.get('raw_message', '')
            
            # 验证消息
            if not self._validate_message(message):
                logger.warning("⚠️ 无效消息，跳过")
                return

            # 更新会话状态（用于延迟发送期间的新消息抢占）
            incoming_seq = self._touch_incoming(conv_key)

            # 必回触发（@ / 叫名字）走快速通道，不交给元 AI 拦截
            force_reply = self._is_force_reply(content, raw_message, message)

            # 群聊“停口令”进入静默窗口（非必回场景）
            if group_id and (not force_reply) and self._is_group_stop_signal(content):
                self._set_group_quiet(group_id)
                logger.info(f"群 {group_id} 进入静默窗口")
                return

            # 群聊处于静默窗口时，非必回消息不回复
            if group_id and (not force_reply) and self._is_group_quiet(group_id):
                logger.debug(f"群 {group_id} 在静默窗口，跳过回复")
                return
            
            # 更新记忆
            if self.memory_system:
                await self.memory_system.add_message(user_id, group_id, message)

            # 分段输入合并窗口：同人短时间连续发言，只处理最后一条
            if group_id and (not force_reply):
                merge_window = self._merge_window_seconds()
                if merge_window > 0:
                    await asyncio.sleep(merge_window)
                    if self._has_newer_incoming(conv_key, incoming_seq):
                        logger.debug(f"合并窗口命中新消息，取消本次回复判定 | user={user_id[-4:]}")
                        return

                    merged_content = await self._merge_recent_user_content(user_id, int(group_id), content)
                    if merged_content:
                        content = merged_content
            
            # 更新回复欲望
            self._update_reply_desire(user_id, group_id, content, raw_message, message)
            
            # 检查是否应该回复
            should_reply = await self._should_reply(user_id, group_id, content, raw_message, message)
            trace_key = f"group_{group_id}" if group_id else f"user_{user_id}"

            # 非 @ 场景增加最小回复间隔，避免句句都回
            if should_reply and group_id and (not force_reply):
                min_gap = self._non_mention_min_interval_seconds()
                if min_gap > 0 and (not self._is_gap_enough(conv_key, min_gap)):
                    logger.debug(f"非@最小间隔未到({min_gap}s)，跳过回复 | user={user_id[-4:]}")
                    should_reply = False

            # 群聊非必回场景：元 AI 再做一层裁决，避免同话题逐人重复回复
            meta_result: Optional[Dict[str, Any]] = None
            extra_wait_seconds = 0
            if should_reply and group_id and (not force_reply) and self.meta_judge:
                recent_messages = []
                if self.memory_system:
                    try:
                        recent_messages = await self.memory_system.get_group_recent(group_id, limit=15)
                    except Exception as e:
                        logger.error(f"读取群聊上下文失败：{e}")

                meta_result = await self.meta_judge.decide(
                    group_id=int(group_id),
                    user_id=user_id,
                    content=content,
                    recent_messages=recent_messages,
                )
                decision = meta_result.get('decision', 'reply')
                if decision == 'skip':
                    logger.debug(
                        f"元AI裁决: {decision} | topic={meta_result.get('topic_key', '-')}, reason={meta_result.get('reason', '-')}, user={user_id[-4:]}"
                    )
                    should_reply = False
                elif decision == 'wait':
                    extra_wait_seconds = int(meta_result.get('wait_seconds', 0) or 0)
                    logger.debug(
                        f"元AI裁决: wait {extra_wait_seconds}s | topic={meta_result.get('topic_key', '-')}, reason={meta_result.get('reason', '-')}, user={user_id[-4:]}"
                    )

            self._log_decision_summary(
                trace_key=trace_key,
                user_id=user_id,
                group_id=group_id,
                force_reply=force_reply,
                final_reply=should_reply,
                meta_result=meta_result,
            )
            
            if should_reply:
                delay_seconds = self._compute_human_delay(
                    user_id=user_id,
                    group_id=group_id,
                    content=content,
                    force_reply=force_reply,
                    extra_wait_seconds=extra_wait_seconds,
                )
                if delay_seconds > 0:
                    logger.debug(f"延迟回复 {delay_seconds:.2f}s | user={user_id[-4:]}")
                    await asyncio.sleep(delay_seconds)

                # 等待期间若有更新消息进入同会话，放弃旧回复，避免抢话
                if (not force_reply) and self._has_newer_incoming(conv_key, incoming_seq):
                    logger.debug(f"检测到更新消息，取消旧回复 | user={user_id[-4:]}")
                    return

                logger.info(f"✓ 回复 {user_id[-4:]}: {content[:50]}...")
                # 生成回复
                message_for_reply = dict(message)
                message_for_reply['message'] = content
                response = await self._generate_response(message_for_reply)
                
                # 发送回复
                if response:
                    await self._send_response(response, message_for_reply)
                    # 仅在实际发送回复后进入冷却
                    self._update_cooldown(user_id, group_id)
                    self._touch_reply(conv_key)

                    # 记录该话题已回复，后续同话题可被元 AI 冷却
                    if group_id and meta_result and self.meta_judge:
                        topic_key = str(meta_result.get('topic_key', '')).strip()
                        if topic_key:
                            self.meta_judge.mark_replied(int(group_id), topic_key)
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

    def _set_decision_trace(self, key: str, **kwargs):
        """更新一次消息判定链路中的关键中间量。"""
        trace = self.decision_trace.get(key, {})
        trace.update(kwargs)
        self.decision_trace[key] = trace

    def _desire_tuning(self) -> Dict[str, Any]:
        """读取回复欲望的调参项。"""
        return self.config.get('features', {}).get('group', {}).get('desire_tuning', {})

    def _normalize_desire_text(self, text: Any) -> str:
        return ''.join(str(text or '').lower().split())

    def _text_similarity(self, left: Any, right: Any) -> float:
        left_text = self._normalize_desire_text(left)
        right_text = self._normalize_desire_text(right)
        if not left_text or not right_text:
            return 0.0
        if left_text == right_text:
            return 1.0
        return SequenceMatcher(None, left_text, right_text).ratio()

    def _decision_log_level(self) -> str:
        """决策日志详细程度：off / concise / detailed。"""
        level = (
            self.config.get('features', {})
            .get('group', {})
            .get('decision_log_level', 'concise')
        )
        level = str(level).strip().lower()
        return level if level in {'off', 'concise', 'detailed'} else 'concise'

    def _log_decision_summary(
        self,
        *,
        trace_key: str,
        user_id: str,
        group_id: Optional[int],
        force_reply: bool,
        final_reply: bool,
        meta_result: Optional[Dict[str, Any]] = None,
    ):
        """输出汇总决策日志（用于演示双层/三层判定）。"""
        level = self._decision_log_level()
        if level == 'off':
            return

        trace = self.decision_trace.get(trace_key, {})
        llm = trace.get('llm_score')
        desire = trace.get('desire')
        threshold = trace.get('threshold')
        combined = trace.get('combined')
        reason = trace.get('reason', '-')
        meta_decision = (meta_result or {}).get('decision', '-') if meta_result else '-'
        meta_reason = (meta_result or {}).get('reason', '-') if meta_result else '-'
        meta_conf = (meta_result or {}).get('confidence', '-') if meta_result else '-'

        if level == 'concise':
            logger.info(
                "决策链 | group=%s user=%s final=%s reason=%s meta=%s",
                group_id if group_id is not None else '-',
                user_id[-4:],
                int(bool(final_reply)),
                reason,
                meta_decision,
            )
            return

        logger.info(
            "决策链 | group=%s user=%s force=%s score[llm=%s desire=%s th=%s comb=%s] meta=%s(conf=%s,reason=%s) final=%s reason=%s",
            group_id if group_id is not None else '-',
            user_id[-4:],
            int(bool(force_reply)),
            f"{llm:.0f}" if isinstance(llm, (int, float)) else '-',
            f"{desire:.0f}" if isinstance(desire, (int, float)) else '-',
            f"{threshold:.0f}" if isinstance(threshold, (int, float)) else '-',
            f"{combined:.0f}" if isinstance(combined, (int, float)) else '-',
            meta_decision,
            f"{meta_conf:.2f}" if isinstance(meta_conf, (int, float)) else meta_conf,
            meta_reason,
            int(bool(final_reply)),
            reason,
        )

    def _touch_incoming(self, conv_key: str) -> int:
        """记录会话新消息并返回当前序号。"""
        state = self.conversation_state.setdefault(
            conv_key,
            {
                'incoming_seq': 0,
                'last_reply_at': None,
            },
        )
        state['incoming_seq'] = int(state.get('incoming_seq', 0)) + 1
        return int(state['incoming_seq'])

    def _has_newer_incoming(self, conv_key: str, snapshot_seq: int) -> bool:
        """检查等待期间是否有更新消息进入会话。"""
        state = self.conversation_state.get(conv_key, {})
        return int(state.get('incoming_seq', 0)) > int(snapshot_seq)

    def _touch_reply(self, conv_key: str):
        """记录最近一次回复时间。"""
        state = self.conversation_state.setdefault(
            conv_key,
            {
                'incoming_seq': 0,
                'last_reply_at': None,
            },
        )
        state['last_reply_at'] = datetime.now()

    def _compute_human_delay(
        self,
        *,
        user_id: str,
        group_id: Optional[int],
        content: str,
        force_reply: bool,
        extra_wait_seconds: int = 0,
    ) -> float:
        """计算更像人的回复延迟。"""
        if not group_id:
            return 0.0

        timing_cfg = (
            self.config.get('features', {})
            .get('group', {})
            .get('human_timing', {})
        )
        if not timing_cfg.get('enabled', True):
            return 0.0

        base = float(timing_cfg.get('base_delay_seconds', 1.6))
        jitter = float(timing_cfg.get('jitter_seconds', 1.0))
        min_delay = float(timing_cfg.get('min_delay_seconds', 0.6))
        max_delay = float(timing_cfg.get('max_delay_seconds', 7.0))
        burst_extra = float(timing_cfg.get('burst_extra_seconds', 1.0))

        # 文本越长，思考稍久
        length_bonus = min(2.4, len(content) / 36.0)
        # 疑问句增加一点停顿
        question_bonus = 0.5 if any(ch in content for ch in ['?', '？', '吗', '怎么', '为什么']) else 0.0
        # 随机抖动避免机械感
        noise = random.uniform(-jitter, jitter)

        conv_key = f"group_{group_id}" if group_id else f"user_{user_id}"
        state = self.conversation_state.get(conv_key, {})
        last_reply_at = state.get('last_reply_at')
        burst_bonus = 0.0
        if isinstance(last_reply_at, datetime):
            gap = (datetime.now() - last_reply_at).total_seconds()
            if gap < 20:
                burst_bonus = burst_extra

        delay = base + length_bonus + question_bonus + noise + burst_bonus
        delay = max(min_delay, min(max_delay, delay))

        if force_reply:
            delay = min(delay, 2.5)

        if extra_wait_seconds > 0:
            delay = max(delay, float(extra_wait_seconds))

        return max(0.0, delay)

    def _merge_window_seconds(self) -> float:
        cfg = self.config.get('features', {}).get('group', {}).get('reply_control', {})
        return float(cfg.get('merge_window_seconds', 4.5))

    def _non_mention_min_interval_seconds(self) -> int:
        cfg = self.config.get('features', {}).get('group', {}).get('reply_control', {})
        return int(cfg.get('non_mention_min_interval_seconds', 18))

    def _is_gap_enough(self, conv_key: str, min_gap_seconds: int) -> bool:
        state = self.conversation_state.get(conv_key, {})
        last_reply_at = state.get('last_reply_at')
        if not isinstance(last_reply_at, datetime):
            return True
        return (datetime.now() - last_reply_at).total_seconds() >= min_gap_seconds

    def _is_group_stop_signal(self, content: str) -> bool:
        cfg = self.config.get('features', {}).get('group', {}).get('reply_control', {})
        stop_words = cfg.get(
            'stop_words',
            ['别回了', '别回复', '不要回', '先别说话', '闭嘴', '停一下'],
        )
        text = (content or '').strip()
        return any(word in text for word in stop_words)

    def _set_group_quiet(self, group_id: int):
        cfg = self.config.get('features', {}).get('group', {}).get('reply_control', {})
        quiet_seconds = int(cfg.get('quiet_mode_seconds', 180))
        self.group_quiet_until[f"group_{group_id}"] = datetime.now() + timedelta(seconds=quiet_seconds)

    def _is_group_quiet(self, group_id: int) -> bool:
        until = self.group_quiet_until.get(f"group_{group_id}")
        if not isinstance(until, datetime):
            return False
        return datetime.now() < until

    async def _merge_recent_user_content(self, user_id: str, group_id: int, current_content: str) -> str:
        """将同一用户短时间分段输入合并为一句，减少连续回复。"""
        if not self.memory_system:
            return current_content

        cfg = self.config.get('features', {}).get('group', {}).get('reply_control', {})
        lookback_seconds = int(cfg.get('merge_lookback_seconds', 12))
        max_parts = int(cfg.get('merge_max_parts', 3))

        try:
            recent = await self.memory_system.get_group_recent(group_id, limit=20)
        except Exception:
            return current_content

        now = datetime.now()
        chunks: List[str] = []
        for item in reversed(recent):
            if str(item.get('speaker_id', item.get('user_id', ''))) != str(user_id):
                continue
            if bool(item.get('is_bot', False)):
                continue

            ts = item.get('time')
            try:
                dt = datetime.fromisoformat(ts) if isinstance(ts, str) else None
            except Exception:
                dt = None
            if not isinstance(dt, datetime):
                continue
            if (now - dt).total_seconds() > lookback_seconds:
                continue

            text = str(item.get('text', '')).strip()
            if text:
                chunks.append(text)
            if len(chunks) >= max_parts:
                break

        if not chunks:
            return current_content
        chunks.reverse()
        merged = ' '.join(chunks).strip()
        return merged or current_content

    def _is_force_reply(self, content: str, raw_message: Optional[str], message: Optional[Dict[str, Any]] = None) -> bool:
        """判断是否属于必须立即回复的场景（不经过元 AI 延迟）。"""
        if self._is_bot_mentioned(content, raw_message, message):
            return True

        # 机器人名字
        bot_names = ['三月七', '三月', '小三月', '77', '七七']
        if any(name in content for name in bot_names):
            return True

        return False

    def _extract_at_targets(self, raw_message: Optional[str]) -> List[str]:
        """提取 CQ:at 目标 QQ 列表。"""
        if not raw_message:
            return []
        import re
        return re.findall(r'\[CQ:at,qq=(\d+)\]', raw_message)

    def _is_addressed_to_others(self, raw_message: Optional[str], message: Optional[Dict[str, Any]] = None) -> bool:
        """是否明确 @ 了他人且未 @ 机器人。"""
        message = message or {}
        targets = self._extract_at_targets(raw_message)
        if not targets:
            return False

        self_qq = str(message.get('self_id', '0'))
        # 消息里存在 @，但不包含 bot 自己，则视为对他人发言
        return self_qq not in targets

    def _is_bot_mentioned(
        self,
        content: str,
        raw_message: Optional[str],
        message: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """仅在确实 @ 到 bot 本体时返回 True。"""
        message = message or {}

        if raw_message:
            import re
            cq_at_pattern = r'\[CQ:at,qq=(\d+)\]'
            matches = re.findall(cq_at_pattern, raw_message)
            self_qq = str(message.get('self_id', '0'))
            if self_qq and self_qq in matches:
                return True

        # 无 CQ 的纯文本兜底
        if '@' in (content or ''):
            return True

        return False
    
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
        now = datetime.now()
        tuning = self._desire_tuning()
        state = self.desire_state.setdefault(
            key,
            {
                'last_event_time': now,
                'last_speaker': None,
                'recent_speakers': deque(maxlen=8),
                'recent_contents': deque(maxlen=8),
                'last_bot_reply': None,
                'last_desire_factors': {},
            },
        )

        recent_contents = state.get('recent_contents')
        if not isinstance(recent_contents, deque):
            recent_contents = deque(maxlen=8)
            state['recent_contents'] = recent_contents
        
        # 获取当前欲望值
        base_desire = float(tuning.get('base_group_desire', 24.0 if group_id else 34.0))
        current = self.reply_desire.get(key, base_desire)

        # 按真实时间衰减，而不是每条消息固定衰减
        last_event_time = state.get('last_event_time', now)
        elapsed_minutes = max(0.0, (now - last_event_time).total_seconds() / 60.0)
        decay_per_minute = float(tuning.get('decay_per_minute', 1.6))
        current = max(0.0, current - decay_per_minute * elapsed_minutes)

        text = (content or '').strip()
        lower_text = text.lower()
        signal_profile: Dict[str, float] = {}

        # @机器人 / 叫名字 / 直接指向，明显提高“想接话”的欲望
        direct_attention = False
        if raw_message:
            import re
            cq_at_pattern = r'\[CQ:at,qq=(\d+)\]'
            matches = re.findall(cq_at_pattern, raw_message)
            self_qq = str(message.get('self_id', '0'))
            if self_qq in matches:
                direct_attention = True
        if '@' in text:
            direct_attention = True
        bot_names = ['三月七', '三月', '小三月', '77', '七七']
        if any(name in text for name in bot_names):
            direct_attention = True
        if direct_attention:
            signal_profile['direct_attention'] = float(tuning.get('direct_attention_boost', 24.0))
        elif any(word in text for word in ['你', '帮我', '请问', '能不能', '可以吗']):
            signal_profile['addressed_to_bot'] = float(tuning.get('addressed_to_bot_boost', 8.0))

        # 询问、请求、带明显对话意图的消息，会把欲望往上拉
        if any(char in text for char in ['?', '？', '吗', '呢', '什么', '怎么', '为什么', '请问']):
            signal_profile['question_boost'] = float(tuning.get('question_boost', 14.0))

        # 情绪、玩笑、感叹会增加接话冲动
        if any(word in text for word in ['哈哈', '笑死', '好玩', '有趣', '嘿嘿', '233', '离谱', '卧槽', '我靠']):
            signal_profile['emotional_boost'] = float(tuning.get('emotion_boost', 8.0))

        # 不是纯填充的话，稍微给一点“愿意接”的倾向
        length = len(text)
        if 12 <= length <= 120:
            signal_profile['content_depth_bonus'] = float(tuning.get('content_depth_bonus', 4.0))
        elif length < 4:
            signal_profile['short_message_penalty'] = float(tuning.get('short_message_penalty', -6.0))

        if any(word in lower_text for word in ['嗯', '哦', '好', '收到', '行', 'ok', '可以', '随便']) and length <= 6:
            signal_profile['filler_penalty'] = float(tuning.get('filler_penalty', -10.0))

        # 群聊活跃度越高，越容易愿意接话
        if group_id:
            speakers = state.get('recent_speakers')
            if not isinstance(speakers, deque):
                speakers = deque(maxlen=8)
            speakers.append(user_id)
            state['recent_speakers'] = speakers

            last_speaker = state.get('last_speaker')
            if last_speaker and last_speaker != user_id:
                signal_profile['speaker_turn_bonus'] = float(tuning.get('speaker_turn_bonus', 3.5))

            unique_speakers = len(set(speakers))
            if unique_speakers >= 2:
                signal_profile['group_activity_bonus'] = min(
                    float(tuning.get('max_activity_bonus', 6.0)),
                    float(tuning.get('activity_per_speaker', 1.8)) * max(1, unique_speakers - 1),
                )

            # 机器人很久没开口，群里更容易产生“该说两句”的冲动
            last_bot_reply = state.get('last_bot_reply')
            if isinstance(last_bot_reply, datetime):
                quiet_seconds = (now - last_bot_reply).total_seconds()
                if quiet_seconds >= float(tuning.get('bot_quiet_threshold_seconds', 180)):
                    signal_profile['bot_quiet_bonus'] = float(tuning.get('bot_quiet_bonus', 3.0))

            state['last_speaker'] = user_id

        # 复读、尾巴式补充、短时间同句，欲望下降
        if recent_contents:
            repeat_hit = max((self._text_similarity(text, prev) for prev in recent_contents), default=0.0)
            if repeat_hit >= 0.86:
                signal_profile['repetition_penalty'] = float(tuning.get('repetition_penalty', -8.0))
            elif repeat_hit >= 0.72:
                signal_profile['near_repeat_penalty'] = float(tuning.get('near_repeat_penalty', -4.0))

        if group_id and not signal_profile:
            signal_profile['ambient_group_interest'] = float(tuning.get('ambient_group_interest', 2.0))

        gain = sum(signal_profile.values())
        current += gain
        
        # 限制最大值
        current = min(100.0, current)

        state['last_event_time'] = now
        recent_contents.append(text)
        state['last_desire_factors'] = signal_profile
        self.reply_desire[key] = current
    
    async def _should_reply(
        self,
        user_id: str,
        group_id: Optional[int],
        content: str,
        raw_message: Optional[str] = None,
        message: Optional[Dict[str, Any]] = None,
    ) -> bool:
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
        key = f"group_{group_id}" if group_id else f"user_{user_id}"
        if not group_id:
            self._set_decision_trace(key, reason='private_auto_reply')
            return True

        # 群聊里明确 @ 他人（且不是 bot）时，不回复
        if self._is_addressed_to_others(raw_message, message):
            self._set_decision_trace(key, reason='addressed_to_others_skip')
            return False
        
        # @机器人必回（只认 @ 到 bot）
        is_mentioned = self._is_bot_mentioned(content, raw_message, message)
        
        if is_mentioned:
            reply_when_mentioned = self.config.get('features', {}).get('group', {}).get('reply_when_mentioned', True)
            if reply_when_mentioned:
                self._set_decision_trace(key, reason='mentioned_force_reply')
                logger.debug(f"{user_id[-4:]} @机器人，必回")
                return True
        
        # 叫机器人名字必回
        bot_names = ['三月七', '三月', '小三月', '77', '七七']
        if any(name in content for name in bot_names):
            self._set_decision_trace(key, reason='name_called_force_reply')
            logger.debug(f"{user_id[-4:]} 叫机器人名字，必回")
            return True

        # 冷却期间不回复（必回场景已在上面提前返回）
        if self._is_in_cooldown(user_id, group_id):
            self._set_decision_trace(key, reason='cooldown_skip')
            logger.debug(f"{user_id[-4:]} 在冷却中，跳过回复")
            return False
        
        # LLM 智能评分
        llm_score = await self._llm_reply_score(content, user_id, group_id)
        
        # 结合欲望值决策
        desire = self.reply_desire.get(key, 0.0)
        base_threshold = self.config.get('features', {}).get('group', {}).get('reply_threshold', 45)
        threshold = float(base_threshold)

        # 动态阈值：短时间内连续回复时提高门槛，群聊多人互动时略降门槛
        state = self.desire_state.get(key, {})
        now = datetime.now()
        last_bot_reply = state.get('last_bot_reply')
        if isinstance(last_bot_reply, datetime):
            gap = (now - last_bot_reply).total_seconds()
            if gap < 20:
                threshold += 15
            elif gap < 60:
                threshold += 8

        recent_speakers = state.get('recent_speakers')
        if isinstance(recent_speakers, deque):
            unique_speakers = len(set(recent_speakers))
            if unique_speakers >= 3:
                threshold -= 6

        question_chars = ['?', '？', '吗', '呢', '什么', '怎么', '为什么']
        if any(char in content for char in question_chars):
            threshold -= 4

        threshold = max(20.0, min(85.0, threshold))
        
        if llm_score >= 80:
            self._set_decision_trace(
                key,
                llm_score=llm_score,
                desire=desire,
                threshold=threshold,
                combined=llm_score,
                reason='llm_high_force_reply',
            )
            logger.debug(f"{user_id[-4:]} LLM {llm_score:.0f}>=80，必回")
            return True

        # 联合评分：减少“单一阈值硬切”带来的生硬感
        combined = llm_score * 0.6 + desire * 0.4
        if combined >= threshold:
            self._set_decision_trace(
                key,
                llm_score=llm_score,
                desire=desire,
                threshold=threshold,
                combined=combined,
                reason='combined_pass',
            )
            logger.debug(
                f"{user_id[-4:]} 综合分 {combined:.0f}>=阈值 {threshold:.0f} (LLM={llm_score:.0f}, desire={desire:.0f})，回复"
            )
            return True

        self._set_decision_trace(
            key,
            llm_score=llm_score,
            desire=desire,
            threshold=threshold,
            combined=combined,
            reason='combined_reject',
        )
        
        logger.debug(
            f"{user_id[-4:]} 综合分 {combined:.0f}<阈值 {threshold:.0f} (LLM={llm_score:.0f}, desire={desire:.0f})，不回"
        )
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

        # 记录机器人最近回复时间，供动态阈值反刷屏使用
        state = self.desire_state.setdefault(
            key,
            {
                'last_event_time': datetime.now(),
                'last_speaker': None,
                'recent_speakers': deque(maxlen=8),
                'last_bot_reply': None,
            },
        )
        state['last_bot_reply'] = datetime.now()
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
