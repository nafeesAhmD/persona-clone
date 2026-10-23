"""Built-in agent tools. Each module registers its tool with app.agent.tool_registry.register()
when imported; importing this package registers them all.

Only read-only, narrowly scoped tools live here. There is deliberately no shell, code
execution, filesystem, database, environment or arbitrary HTTP tool.
"""

from app.agent.tools import (  # noqa: F401
    calculator,
    clone_info,
    conversation_context,
    date_time,
    knowledge_search,
    memory_search,
    web_search,
)
