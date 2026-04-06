# Memory Feature
"""
记忆功能模块
"""

import logging
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MemorySystem:
    """记忆系统"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.memory_dir = config.get('features', {}).get('memory', {}).get('dir', 'memory')
        self.auto_memory_dir = config.get('features', {}).get('memory', {}).get('auto_dir', 'memory_auto')
        self.short_term_size = config.get('features', {}).get('memory', {}).get('short_term_size', 100)
        
        # 确保目录存在
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.auto_memory_dir, exist_ok=True)
        
        # 记忆缓存
        self.short_term: Dict[str, List[Dict]] = {}
        self.long_term: Dict[str, str] = {}
    
    async def initialize(self):
        """初始化"""
        logger.info(f"✓ 记忆系统已初始化 (目录:{self.memory_dir})")
        await self.load_all()
    
    async def load_all(self):
        """加载所有记忆"""
        try:
            long_term_file = os.path.join(self.memory_dir, 'long_term.md')
            if os.path.exists(long_term_file):
                with open(long_term_file, 'r', encoding='utf-8') as f:
                    self.long_term['global'] = f.read()
                logger.debug("已加载长期记忆")

            self._load_auto_memory()
        except Exception as e:
            logger.error(f"加载记忆失败：{e}")
    
    async def save_all(self):
        """保存所有记忆"""
        try:
            # 保存长期记忆
            long_term_file = os.path.join(self.memory_dir, 'long_term.md')
            if 'global' in self.long_term:
                with open(long_term_file, 'w', encoding='utf-8') as f:
                    f.write(self.long_term['global'])
            
            # 保存自动记忆
            for key, messages in self.short_term.items():
                auto_file = self._auto_memory_path_for_key(key)
                if not auto_file:
                    continue

                os.makedirs(os.path.dirname(auto_file), exist_ok=True)
                compact_messages = [self._compact_entry(message) for message in messages[-self.short_term_size:]]
                with open(auto_file, 'w', encoding='utf-8') as f:
                    json.dump(compact_messages, f, ensure_ascii=False, indent=2)

            self._cleanup_legacy_auto_files()
            
            logger.debug("✓ 记忆已保存")
        except Exception as e:
            logger.error(f"保存记忆失败：{e}")
    
    async def add_message(self, user_id: str, group_id: Optional[int], message: Dict[str, Any]):
        """添加消息到记忆"""
        key = f"group_{group_id}_user_{user_id}" if group_id else f"user_{user_id}"
        timeline_key = f"group_{group_id}_timeline" if group_id else key
        entry = self._build_entry(user_id, group_id, message, is_bot=False)
        
        if key not in self.short_term:
            self.short_term[key] = []
        if timeline_key not in self.short_term:
            self.short_term[timeline_key] = []
        
        self.short_term[key].append(entry)
        self.short_term[timeline_key].append(entry)
        
        # 保持最近 N 条
        if len(self.short_term[key]) > self.short_term_size:
            self.short_term[key] = self.short_term[key][-self.short_term_size:]
        if len(self.short_term[timeline_key]) > self.short_term_size:
            self.short_term[timeline_key] = self.short_term[timeline_key][-self.short_term_size:]

    async def add_bot_message(self, group_id: Optional[int], content: str, bot_id: str = 'bot', bot_name: str = 'bot'):
        """添加机器人回复到记忆，保证上下文里有 assistant 视角。"""
        key = f"group_{group_id}_user_{bot_id}" if group_id else f"user_{bot_id}"
        timeline_key = f"group_{group_id}_timeline" if group_id else key
        message = {
            'user_id': bot_id,
            'group_id': group_id,
            'message': content,
            'sender': {
                'nickname': bot_name,
                'card': bot_name,
                'role': 'assistant',
            },
        }
        entry = self._build_entry(bot_id, group_id, message, is_bot=True)

        if key not in self.short_term:
            self.short_term[key] = []
        if timeline_key not in self.short_term:
            self.short_term[timeline_key] = []

        self.short_term[key].append(entry)
        self.short_term[timeline_key].append(entry)

        if len(self.short_term[key]) > self.short_term_size:
            self.short_term[key] = self.short_term[key][-self.short_term_size:]
        if len(self.short_term[timeline_key]) > self.short_term_size:
            self.short_term[timeline_key] = self.short_term[timeline_key][-self.short_term_size:]
    
    async def get_recent(self, user_id: str, group_id: Optional[int], limit: int = 5) -> List[Dict]:
        """获取最近消息（单个用户）"""
        key = f"group_{group_id}_user_{user_id}" if group_id else f"user_{user_id}"
        
        if key not in self.short_term:
            return []
        
        return self.short_term[key][-limit:]
    
    async def get_group_recent(self, group_id: int, limit: int = 10) -> List[Dict]:
        """
        获取群聊最近消息（整合所有用户的发言）
        
        Args:
            group_id: 群聊 ID
            limit: 返回消息数量
            
        Returns:
            按时间排序的群聊消息列表（包含不同用户）
        """
        if not group_id:
            return []

        # 优先使用群时间线（包含机器人消息）
        timeline_key = f"group_{group_id}_timeline"
        if timeline_key in self.short_term:
            return self.short_term[timeline_key][-limit:]
        
        # 收集群里所有用户的消息
        all_messages = []
        prefix = f"group_{group_id}_user_"
        
        for key, messages in self.short_term.items():
            if key.startswith(prefix):
                # 提取用户 ID
                user_id = key.replace(prefix, '')
                for msg in messages:
                    msg_copy = msg.copy()
                    msg_copy['user_id'] = user_id
                    all_messages.append(msg_copy)
        
        # 按时间排序
        all_messages.sort(key=lambda x: x.get('time', ''))
        
        # 返回最近 limit 条
        return all_messages[-limit:]

    def _load_auto_memory(self):
        """从磁盘加载自动记忆，兼容旧版扁平文件和新版结构化目录。"""
        if not os.path.isdir(self.auto_memory_dir):
            return

        loaded_keys = set()

        for file_path in self._iter_auto_memory_files(structured_only=True):
            key = self._auto_memory_key_from_path(file_path)
            if not key:
                continue
            self._load_auto_memory_file(file_path, key)
            loaded_keys.add(key)

        for file_path in self._iter_auto_memory_files(structured_only=False):
            relative_path = os.path.relpath(file_path, self.auto_memory_dir).replace('\\', '/')
            if relative_path.startswith('groups/') or relative_path.startswith('users/'):
                continue

            key = self._auto_memory_key_from_path(file_path)
            if not key or key in loaded_keys:
                continue

            self._load_auto_memory_file(file_path, key)
            loaded_keys.add(key)

    def _iter_auto_memory_files(self, structured_only: bool) -> List[str]:
        files: List[str] = []
        for root, _, filenames in os.walk(self.auto_memory_dir):
            for filename in filenames:
                if not filename.endswith('.json'):
                    continue

                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, self.auto_memory_dir).replace('\\', '/')
                is_structured = relative_path.startswith('groups/') or relative_path.startswith('users/')
                if structured_only and not is_structured:
                    continue
                if (not structured_only) and is_structured:
                    continue
                files.append(file_path)

        files.sort()
        return files

    def _load_auto_memory_file(self, file_path: str, key: str):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                logger.warning(f"自动记忆文件格式异常，已跳过：{file_path}")
                return

            entries = [item for item in data if isinstance(item, dict)]
            if not entries:
                return

            if key not in self.short_term:
                self.short_term[key] = []

            self.short_term[key].extend(entries)
            self.short_term[key] = self.short_term[key][-self.short_term_size:]
        except Exception as e:
            logger.error(f"加载自动记忆失败：{file_path}，{e}")

    def _auto_memory_key_from_path(self, file_path: str) -> Optional[str]:
        relative_path = os.path.relpath(file_path, self.auto_memory_dir).replace('\\', '/')
        parts = relative_path.split('/')
        filename = parts[-1]

        if relative_path.startswith('groups/'):
            if len(parts) >= 3 and parts[2] == 'timeline.json':
                group_id = parts[1]
                return f"group_{group_id}_timeline"
            if len(parts) >= 4 and parts[2] == 'users' and filename.endswith('.json'):
                group_id = parts[1]
                user_id = os.path.splitext(filename)[0]
                return f"group_{group_id}_user_{user_id}"

        if relative_path.startswith('users/') and filename.endswith('.json'):
            user_id = os.path.splitext(filename)[0]
            return f"user_{user_id}"

        if filename.startswith('group_') and filename.endswith('_timeline.json'):
            group_id = filename[len('group_'):-len('_timeline.json')]
            return f"group_{group_id}_timeline"

        if filename.startswith('group_') and '_user_' in filename and filename.endswith('.json'):
            base_name = filename[:-5]
            group_part, user_part = base_name.split('_user_', 1)
            group_id = group_part[len('group_'):]
            return f"group_{group_id}_user_{user_part}"

        if filename.startswith('user_') and filename.endswith('.json'):
            user_id = filename[len('user_'):-len('.json')]
            return f"user_{user_id}"

        return None

    def _auto_memory_path_for_key(self, key: str) -> Optional[str]:
        if key.endswith('_timeline') and key.startswith('group_'):
            group_id = key[len('group_'):-len('_timeline')]
            return os.path.join(self.auto_memory_dir, 'groups', group_id, 'timeline.json')

        if key.startswith('group_') and '_user_' in key:
            group_part, user_part = key.split('_user_', 1)
            group_id = group_part[len('group_'):]
            return os.path.join(self.auto_memory_dir, 'groups', group_id, 'users', f'{user_part}.json')

        if key.startswith('user_'):
            user_id = key[len('user_'):]
            return os.path.join(self.auto_memory_dir, 'users', f'{user_id}.json')

        return os.path.join(self.auto_memory_dir, f'{key}.json')

    def _compact_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            'time': entry.get('time'),
            'group_id': entry.get('group_id'),
            'user_id': entry.get('user_id'),
            'speaker_id': entry.get('speaker_id'),
            'speaker_name': entry.get('speaker_name'),
            'is_bot': entry.get('is_bot', False),
            'text': entry.get('text', ''),
        }

        message = entry.get('message', {})
        if isinstance(message, dict):
            source = {}
            for field in ['message_id', 'real_id', 'message_seq', 'real_seq', 'message_type', 'sub_type', 'group_name']:
                value = message.get(field)
                if value is not None:
                    source[field] = value

            sender = message.get('sender', {})
            if isinstance(sender, dict):
                sender_meta = {}
                for field in ['user_id', 'nickname', 'card', 'role']:
                    value = sender.get(field)
                    if value is not None:
                        sender_meta[field] = value
                if sender_meta:
                    source['sender'] = sender_meta

            raw_message = message.get('raw_message')
            if raw_message:
                source['raw_message'] = raw_message

            if source:
                compact['source'] = source

        return compact

    def _cleanup_legacy_auto_files(self):
        """删除旧版扁平自动记忆文件，避免新旧格式并存。"""
        if not os.path.isdir(self.auto_memory_dir):
            return

        for filename in os.listdir(self.auto_memory_dir):
            if not filename.endswith('.json'):
                continue

            legacy_path = os.path.join(self.auto_memory_dir, filename)
            if os.path.isfile(legacy_path):
                try:
                    os.remove(legacy_path)
                except Exception as e:
                    logger.warning(f"清理旧自动记忆失败：{legacy_path}，{e}")

    async def get_group_profile(self, group_id: int, limit: int = 50) -> Dict[str, Any]:
        """
        获取群聊画像：参与者、发言计数、最近活跃者。
        """
        if not group_id:
            return {'participants': [], 'total_messages': 0}

        recent_messages = await self.get_group_recent(group_id, limit=limit)
        stats: Dict[str, Dict[str, Any]] = {}
        for msg in recent_messages:
            speaker_id = str(msg.get('speaker_id', msg.get('user_id', 'unknown')))
            speaker_name = msg.get('speaker_name', speaker_id)
            is_bot = bool(msg.get('is_bot', False))

            if speaker_id not in stats:
                stats[speaker_id] = {
                    'speaker_id': speaker_id,
                    'speaker_name': speaker_name,
                    'is_bot': is_bot,
                    'message_count': 0,
                }
            stats[speaker_id]['message_count'] += 1

        participants = sorted(stats.values(), key=lambda x: x['message_count'], reverse=True)
        return {
            'participants': participants,
            'total_messages': len(recent_messages),
        }

    def _extract_text(self, content: Any) -> str:
        """将 OneBot message 字段统一为纯文本。"""
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

    def _build_entry(self, user_id: str, group_id: Optional[int], message: Dict[str, Any], is_bot: bool) -> Dict[str, Any]:
        """构建统一记忆条目，便于后续身份识别与群上下文摘要。"""
        sender = message.get('sender', {}) if isinstance(message, dict) else {}
        speaker_name = sender.get('card') or sender.get('nickname') or str(user_id)
        text = self._extract_text(message.get('message', '') if isinstance(message, dict) else '')
        return {
            'time': datetime.now().isoformat(),
            'group_id': group_id,
            'user_id': str(user_id),
            'speaker_id': str(user_id),
            'speaker_name': speaker_name,
            'is_bot': is_bot,
            'text': text,
            'message': message,
        }


class MemoryFeature:
    """记忆功能模块"""
    
    def __init__(self, config: Dict[str, Any], engine):
        self.config = config
        self.engine = engine
        self.name = "memory"
        self.is_initialized = False
        
        self.memory_system = MemorySystem(config)
    
    async def initialize(self):
        """初始化"""
        await self.memory_system.initialize()
        logger.info("✓ 记忆功能已初始化")
        self.is_initialized = True
    
    async def shutdown(self):
        """关闭"""
        try:
            await self.memory_system.save_all()
        except Exception as e:
            logger.error(f"保存记忆失败：{e}")
        logger.info("记忆功能已关闭")
        self.is_initialized = False
