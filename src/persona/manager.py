import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class PersonaManager:
    """人设管理器：负责定位、加载、回退系统提示词。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def load_prompt(self) -> str:
        """加载系统提示词。优先级：显式提示词 > 人设文件 > 通用默认提示词。"""
        explicit_prompt = self._get_explicit_prompt()
        if explicit_prompt:
            return explicit_prompt

        persona_name, persona_file = self.get_persona_source()
        resolved = self._resolve_persona_path(persona_name, persona_file)
        if resolved and resolved.exists():
            try:
                return resolved.read_text(encoding='utf-8')
            except Exception as e:
                logger.warning(f"加载人设文件失败: {resolved} | {e}")

        logger.info("未命中人设文件，使用通用默认提示词")
        return self.get_default_prompt()

    def get_persona_source(self) -> Tuple[str, Optional[str]]:
        """返回人设名与配置中的文件路径。"""
        persona_cfg = self.config.get('persona', {})
        bot_cfg = self.config.get('bot', {})

        persona_name = (
            os.getenv('BOT_PERSONA')
            or persona_cfg.get('name')
            or bot_cfg.get('character')
            or 'default'
        )

        persona_file = (
            os.getenv('BOT_PERSONA_FILE')
            or persona_cfg.get('file')
            or bot_cfg.get('identity_file')
        )

        return str(persona_name), str(persona_file) if persona_file else None

    def _get_explicit_prompt(self) -> Optional[str]:
        chat_cfg = self.config.get('features', {}).get('chat', {})
        persona_cfg = self.config.get('persona', {})

        prompt = (
            os.getenv('BOT_SYSTEM_PROMPT')
            or persona_cfg.get('system_prompt')
            or chat_cfg.get('system_prompt')
        )
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
        return None

    def _resolve_persona_path(self, persona_name: str, persona_file: Optional[str]) -> Optional[Path]:
        project_root = self._get_project_root()

        if persona_file:
            path = Path(persona_file)
            return path if path.is_absolute() else project_root / path

        if not persona_name:
            return None

        return project_root / 'config' / 'characters' / f'{persona_name}.md'

    def _get_project_root(self) -> Path:
        try:
            import sys
            main_file = getattr(sys.modules.get('__main__'), '__file__', None)
            if main_file:
                return Path(main_file).parent
        except Exception:
            pass
        return Path.cwd()

    def get_default_prompt(self) -> str:
        """不绑定具体 IP 的通用默认提示词。"""
        return (
            "你是一个可靠、友善、清晰的中文智能助手。\n\n"
            "【目标】\n"
            "- 优先准确理解用户意图\n"
            "- 给出可执行、可验证的建议\n"
            "- 对不确定信息保持诚实\n\n"
            "【表达风格】\n"
            "- 简洁自然，避免冗长\n"
            "- 先结论后细节\n"
            "- 必要时给步骤和注意事项\n\n"
            "【行为约束】\n"
            "- 不编造事实或能力\n"
            "- 无法确定时明确说明并给替代方案\n"
            "- 保持礼貌、稳定、专业"
        )
