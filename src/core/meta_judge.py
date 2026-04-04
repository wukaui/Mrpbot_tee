import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetaJudge:
    """元AI裁决器：在群聊场景下决定 reply/wait/skip。"""

    def __init__(self, config: Dict[str, Any], llm_client: Any):
        self.config = config
        self.llm_client = llm_client
        self.meta_cfg = config.get('features', {}).get('group', {}).get('meta_ai', {})
        self.topic_reply_at: Dict[str, datetime] = {}

    def is_enabled(self) -> bool:
        return bool(self.meta_cfg.get('enabled', True))

    def _topic_min_interval_seconds(self) -> int:
        return int(self.meta_cfg.get('topic_min_interval_seconds', 45))

    def _max_context_messages(self) -> int:
        return int(self.meta_cfg.get('max_context_messages', 12))

    def _default_wait_seconds(self) -> int:
        return int(self.meta_cfg.get('default_wait_seconds', 12))

    def _min_confidence(self) -> float:
        return float(self.meta_cfg.get('min_confidence', 0.72))

    def _similarity_threshold(self) -> float:
        return float(self.meta_cfg.get('duplicate_similarity_threshold', 0.68))

    def _fallback_topic_key(self, content: str) -> str:
        text = re.sub(r'\s+', '', content.lower())
        text = re.sub(r'[^\u4e00-\u9fa5a-z0-9]', '', text)
        return text[:24] or 'general'

    def _normalize_text(self, text: str) -> str:
        text = re.sub(r'\s+', '', (text or '').lower())
        return re.sub(r'[^\u4e00-\u9fa5a-z0-9]', '', text)

    def _is_question(self, text: str) -> bool:
        question_chars = ['?', '？', '吗', '呢', '什么', '怎么', '为什么', '请问']
        return any(char in (text or '') for char in question_chars)

    def _similarity(self, a: str, b: str) -> float:
        a = self._normalize_text(a)
        b = self._normalize_text(b)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0

        # 字符集合相似度（轻量，无额外依赖）
        sa, sb = set(a), set(b)
        inter = len(sa & sb)
        union = len(sa | sb) or 1
        return inter / union

    def _count_repetition_hits(self, content: str, recent_messages: List[Dict[str, Any]]) -> int:
        """统计当前消息与最近群消息的重复程度，用作人类式裁决的锚点。"""
        non_bot_recent = [m for m in recent_messages if not bool(m.get('is_bot', False))]
        hits = 0
        for m in non_bot_recent[-6:]:
            txt = str(m.get('text', ''))
            if self._similarity(content, txt) >= self._similarity_threshold():
                hits += 1
        return hits

    def _build_human_context(self, *, group_id: int, user_id: str, content: str, recent_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """把群聊上下文整理成人类容易判断的信号。"""
        non_bot_recent = [m for m in recent_messages if not bool(m.get('is_bot', False))]
        repetition_hits = self._count_repetition_hits(content, recent_messages)
        recent_speakers: List[str] = []
        seen_speakers = set()

        for msg in recent_messages[-6:]:
            speaker = str(msg.get('speaker_name') or msg.get('speaker_id') or msg.get('user_id', 'unknown'))
            if speaker not in seen_speakers:
                recent_speakers.append(speaker)
                seen_speakers.add(speaker)

        text = (content or '').strip()
        length = len(text)
        question_like = self._is_question(text)
        emotional_markers = any(word in text for word in ['哈哈', '笑死', '哎', '啊', '卧槽', '我靠', '草', '哭', '难受', '离谱'])
        filler_like = any(word in text for word in ['嗯', '哦', '好', '收到', '行', 'ok', 'OK', '可以', '随便']) and length <= 6
        directness = 'high' if question_like or '你' in text or '吗' in text else 'medium'

        return {
            'group_id': group_id,
            'user_id': user_id,
            'content_length': length,
            'short_message': length <= 10,
            'question_like': question_like,
            'emotional_markers': emotional_markers,
            'filler_like': filler_like,
            'recent_non_bot_count': len(non_bot_recent),
            'recent_speakers': recent_speakers[-5:],
            'speaker_diversity': len(seen_speakers),
            'repetition_hits': repetition_hits,
            'topic_cooldown': self._topic_in_cooldown(group_id, self._fallback_topic_key(content)),
            'directness': directness,
        }

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        text = text.strip()
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        match = re.search(r'\{[\s\S]*\}', text)
        if not match:
            return None

        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
        return None

    def _topic_in_cooldown(self, group_id: int, topic_key: str) -> bool:
        key = f"group_{group_id}:{topic_key}"
        last = self.topic_reply_at.get(key)
        if not last:
            return False
        return datetime.now() - last < timedelta(seconds=self._topic_min_interval_seconds())

    def mark_replied(self, group_id: int, topic_key: str):
        key = f"group_{group_id}:{topic_key}"
        self.topic_reply_at[key] = datetime.now()

    async def decide(
        self,
        *,
        group_id: int,
        user_id: str,
        content: str,
        recent_messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        返回结构化裁决：
        {
          decision: reply|wait|skip,
          topic_key: str,
          wait_seconds: int,
          reason: str
        }
        """
        fallback_topic = self._fallback_topic_key(content)
        human_context = self._build_human_context(
            group_id=group_id,
            user_id=user_id,
            content=content,
            recent_messages=recent_messages,
        )

        if not self.is_enabled():
            return {
                'decision': 'reply',
                'topic_key': fallback_topic,
                'wait_seconds': 0,
                'reason': 'meta_ai_disabled',
            }

        # 问句优先回复，避免“不点名就不回”
        if human_context['question_like']:
            return {
                'decision': 'reply',
                'topic_key': fallback_topic,
                'wait_seconds': 0,
                'reason': 'question_priority',
            }

        # 最近上下文不足时不过度拦截，但仍保留轻量锚点
        if human_context['recent_non_bot_count'] < 3:
            return {
                'decision': 'reply',
                'topic_key': fallback_topic,
                'wait_seconds': 0,
                'reason': 'context_insufficient',
            }

        duplicate_hits = human_context['repetition_hits']

        if self._topic_in_cooldown(group_id, fallback_topic) and duplicate_hits >= 1:
            return {
                'decision': 'wait',
                'topic_key': fallback_topic,
                'wait_seconds': self._default_wait_seconds(),
                'reason': 'topic_cooldown_hit',
            }

        if not getattr(self.llm_client, 'client', None):
            return {
                'decision': 'reply',
                'topic_key': fallback_topic,
                'wait_seconds': 0,
                'reason': 'llm_client_unavailable',
            }

        ctx_lines: List[str] = []
        for m in recent_messages[-self._max_context_messages():]:
            speaker = m.get('speaker_name') or m.get('speaker_id') or m.get('user_id', 'unknown')
            text = str(m.get('text', ''))[:80]
            if not text:
                continue
            ctx_lines.append(f"[{speaker}] {text}")
        context_text = '\n'.join(ctx_lines) if ctx_lines else '(无)'

        system_prompt = (
            '你是群聊里的资深成员兼节奏协调者，负责判断这条消息现在要不要接。\n'
            '请用更像人的方式思考：看语气、对话意图、话题新鲜度、是否轮到你说、以及是否刚刚已经有人接过。\n'
            '你不是在做机械过滤，而是在模拟一个有经验的人会不会开口、要不要先等等、或者干脆保持安静。\n'
            '默认倾向 reply；只有明显该停、该等等、或明显在重复同一件事时，才选择 wait 或 skip。\n'
            '你必须只输出 JSON，格式如下：\n'
            '{"decision":"reply|wait|skip","topic_key":"短主题","wait_seconds":0,"confidence":0.0,"reason":"简短原因","human_reading":"一句人类式判断"}'
        )

        user_prompt = (
            f"群ID: {group_id}\n"
            f"当前用户: {user_id}\n"
            f"当前消息: {content[:200]}\n\n"
            f"人类裁决信号: {json.dumps(human_context, ensure_ascii=False)}\n\n"
            f"最近群上下文:\n{context_text}\n\n"
            "判定规则：\n"
            "1) 先按人的直觉判断，不要只盯关键词。\n"
            "2) 如果是问句、明显抛给群体的问题、情绪表达、或新信息，通常 reply。\n"
            "3) 如果只是复读、寒暄尾巴、无信息填充、或者明显重复刚讨论过的内容，可以 wait 或 skip。\n"
            "4) 如果群里刚有人接过相同话题，且你再接只会重复，就更像人会先等等。\n"
            "5) topic_key 要短而稳，像人给这个话题起的临时标签。\n"
            "6) confidence 代表你有多像一个熟人一样确信这个判断，0-1 之间。"
        )

        try:
            response = await self.llm_client.client.chat.completions.create(
                model=self.llm_client.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                temperature=0.35,
                max_tokens=120,
            )
            text = (response.choices[0].message.content or '').strip()
            parsed = self._extract_json(text)
            if not parsed:
                logger.debug("MetaJudge JSON 解析失败，回退 reply")
                return {
                    'decision': 'reply',
                    'topic_key': fallback_topic,
                    'wait_seconds': 0,
                    'reason': 'json_parse_failed',
                }

            decision = str(parsed.get('decision', 'reply')).lower()
            if decision not in ('reply', 'wait', 'skip'):
                decision = 'reply'

            topic_key = str(parsed.get('topic_key', fallback_topic)).strip() or fallback_topic
            wait_seconds = int(parsed.get('wait_seconds', 0) or 0)
            confidence = float(parsed.get('confidence', 0.5) or 0.5)
            reason = str(parsed.get('reason', 'meta_judge')).strip()[:80]
            human_reading = str(parsed.get('human_reading', '')).strip()[:80]

            # 低置信裁决不拦截，避免“该回不回”
            if decision in ('wait', 'skip') and confidence < self._min_confidence():
                decision = 'reply'
                wait_seconds = 0
                reason = 'low_confidence_fallback'

            # 若模型仍判 reply，但同话题刚被回复过，则降级为 wait，让节奏更像人
            if self._topic_in_cooldown(group_id, topic_key) and decision == 'reply' and duplicate_hits >= 1:
                decision = 'wait'
                wait_seconds = max(wait_seconds, self._default_wait_seconds())
                reason = 'topic_cooldown_hit_after_llm'

            if human_reading:
                reason = f"{reason} | {human_reading}"[:120]

            return {
                'decision': decision,
                'topic_key': topic_key,
                'wait_seconds': max(0, wait_seconds),
                'reason': reason,
            }

        except Exception as e:
            logger.error(f"MetaJudge 调用失败：{e}")
            return {
                'decision': 'reply',
                'topic_key': fallback_topic,
                'wait_seconds': 0,
                'reason': 'meta_judge_error',
            }
