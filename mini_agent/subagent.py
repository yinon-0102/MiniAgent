"""子 Agent：定义独立循环所使用的工具配置。"""

from mini_agent.tools import TOOL_SCHEMAS
from mini_agent.tool_registry import TOOL_HANDLERS
from mini_agent.agent import agent_loop
from mini_agent.prompts import SUB_SYSTEM_PROMPT


# 明确列出子 Agent 可以使用的工具。
SUB_TOOL_NAMES = {
    "cmd",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
}

# 提供给模型的工具描述。
SUB_TOOLS = [
    schema
    for schema in TOOL_SCHEMAS
    if schema["function"]["name"] in SUB_TOOL_NAMES
]

# 程序实际执行时使用的函数映射。
SUB_HANDLERS = {
    name: TOOL_HANDLERS[name]
    for name in SUB_TOOL_NAMES
}


def run_subagent(llm, prompt: str) -> str:
    """使用独立上下文完成子任务，返回最终回答或停止说明。"""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("子任务描述必须是非空字符串。")

    # 每次调用都新建列表，不复制父 Agent 的对话。
    sub_messages = [
        {
            "role": "system",
            "content": SUB_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": prompt.strip(),
        },
    ]

    print("\n[子 Agent 开始]")

    answer = agent_loop(
        llm,
        sub_messages,
        tool_schemas=SUB_TOOLS,
        tool_handlers=SUB_HANDLERS,
        max_turns=30,
        agent_name="子 Agent",
    )

    print("[子 Agent 返回]")
    return answer or "子 Agent 未返回文本内容。"


TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "task",
        "description": (
            "将一个明确、相对独立的子任务交给子 Agent。"
            "子 Agent 不知道当前对话历史，"
            "请提供目标、必要背景、约束和返回要求。"
            "同步等待完成，返回最终文本或停止说明。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "minLength": 1,
                    "description": "完整的子任务描述。",
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
}
