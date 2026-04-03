# LLM Client
"""
LLM 客户端

支持：
- DeepSeek
- OpenAI 兼容 API
"""

import logging
import os
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.persona import PersonaManager

logger = logging.getLogger(__name__)


class LLMClient:
    """
    LLM 客户端
    
    Attributes:
        config: 配置字典
        api_key: API Key
        base_url: API 地址
        model: 模型名称
        is_initialized: 初始化状态
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化 LLM 客户端
        
        Args:
            config: 配置字典
        """
        self.config = config
        
        # 配置（优先级：环境变量 > 配置文件）
        self.api_key = os.getenv('DEEPSEEK_API_KEY') or config.get('llm', {}).get('api_key', '')
        self.base_url = os.getenv('DEEPSEEK_BASE_URL') or config.get('llm', {}).get('base_url', 'https://api.deepseek.com')
        self.model = os.getenv('DEEPSEEK_MODEL') or config.get('llm', {}).get('model', 'deepseek-chat')
        self.timeout = config.get('llm', {}).get('timeout', 30)
        self.max_retries = config.get('llm', {}).get('max_retries', 3)
        
        # 人设系统（独立模块）
        self.persona_manager = PersonaManager(config)
        self.character, self.identity_file = self.persona_manager.get_persona_source()
        self.system_prompt = self.persona_manager.load_prompt()
        
        self.is_initialized = False
        self.client: Optional[Any] = None
    
    async def initialize(self):
        """初始化客户端"""
        try:
            logger.info(f"初始化 LLM 客户端...")
            logger.info(f"  API 地址：{self.base_url}")
            logger.info(f"  模型：{self.model}")
            
            if not self.api_key:
                logger.warning("⚠️ 未设置 API Key，LLM 功能将不可用")
                return
            
            # 导入 OpenAI 客户端
            import openai
            self.client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
            
            self.is_initialized = True
            logger.info("✓ LLM 客户端初始化成功")
            
        except Exception as e:
            logger.error(f"LLM 客户端初始化失败：{e}", exc_info=True)
            self.is_initialized = False
    
    async def close(self):
        """关闭客户端"""
        if self.client and hasattr(self.client, 'close'):
            try:
                await self.client.close()
                logger.info("✓ LLM 客户端已关闭")
            except Exception as e:
                logger.error(f"关闭 LLM 客户端失败：{e}")
        
        self.is_initialized = False
    
    async def chat(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        """
        聊天
        
        Args:
            message: 用户消息
            context: 上下文
            
        Returns:
            AI 回复
        """
        if not self.is_initialized:
            logger.warning("LLM 未初始化")
            return None
        
        if not self.client:
            logger.warning("LLM 客户端未创建")
            return None
        
        try:
            # 构建消息历史
            messages = self._build_messages(message, context)
            
            # 调用 API
            max_tokens = self.config.get('features', {}).get('chat', {}).get('max_tokens', 1024)
            temperature = self.config.get('features', {}).get('chat', {}).get('temperature', 0.7)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                logger.debug(f"LLM 回复：{content[:50]}...")
                return content
            else:
                logger.warning("LLM 返回空响应")
                return None
                
        except Exception as e:
            logger.error(f"LLM 聊天失败：{e}", exc_info=True)
            return None
    
    def _build_messages(self, message: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        构建消息历史
        
        Args:
            message: 用户消息
            context: 上下文
            
        Returns:
            消息列表
        """
        messages = []
        
        # 1. 系统提示（从人设文件加载）
        messages.append({'role': 'system', 'content': self.system_prompt})
        
        # 2. 最近消息
        recent = context.get('recent_messages', [])
        for msg in recent:
            try:
                msg_content = self._extract_text_from_memory(msg)
                if not msg_content.strip():
                    continue

                is_bot = bool(msg.get('is_bot', False))
                role = 'assistant' if is_bot else 'user'
                speaker_name = msg.get('speaker_name', '')
                if role == 'user' and speaker_name:
                    msg_content = f"[{speaker_name}] {msg_content}"

                messages.append({'role': role, 'content': msg_content})
            except Exception as e:
                logger.error(f"解析消息失败：{e}")

        # 2.5 群聊画像摘要，辅助模型理解“谁更活跃、当前是几人对话”
        group_profile = context.get('group_profile', {})
        participants = group_profile.get('participants', [])
        if participants:
            top_speakers = participants[:5]
            speaker_desc = ', '.join(
                [f"{p.get('speaker_name', p.get('speaker_id', 'unknown'))}:{p.get('message_count', 0)}" for p in top_speakers]
            )
            profile_prompt = f"群聊画像：最近{group_profile.get('total_messages', 0)}条消息，活跃成员(发言数)={speaker_desc}"
            messages.append({'role': 'system', 'content': profile_prompt})
        
        # 3. 当前消息
        messages.append({'role': 'user', 'content': message})
        
        logger.debug(f"构建消息历史：{len(messages)}条")
        return messages

    def _extract_text_from_memory(self, msg: Dict[str, Any]) -> str:
        """兼容旧版/新版记忆结构，提取文本内容。"""
        if 'text' in msg and isinstance(msg.get('text'), str):
            return msg.get('text', '')

        payload = msg.get('message', {})
        if isinstance(payload, dict):
            content = payload.get('message', '')
        else:
            content = payload

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':
                    text_parts.append(part.get('data', {}).get('text', ''))
                elif isinstance(part, str):
                    text_parts.append(part)
            return ''.join(text_parts)
        return str(content or '')
    
    def reload_identity(self):
        """
        重新加载人设文件（用于角色切换）
        """
        self.character, self.identity_file = self.persona_manager.get_persona_source()
        self.system_prompt = self.persona_manager.load_prompt()
        logger.info(f"已重新加载人设：{self.character}")
