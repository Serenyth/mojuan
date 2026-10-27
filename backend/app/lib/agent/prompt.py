"""兼容转发：内置提示词常量现在住在顶层 `app.prompts`（避免 settings 与
agent 包互相导入造成循环依赖）。这里仅保留转发，别再往这里写内容。
"""

from app.prompts import DEFAULT_AGENT_SYSTEM_PROMPT

__all__ = ["DEFAULT_AGENT_SYSTEM_PROMPT"]
