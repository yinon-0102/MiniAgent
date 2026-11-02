"""终端入口：初始化一次，在同一会话中持续接收问题。"""

from functools import partial
from pathlib import Path

from mini_agent.agent import agent_loop
from mini_agent.config import Settings
from mini_agent.llm_client import LLMClient
from mini_agent.hooks import trigger_hooks
from mini_agent.prompts import SYSTEM_PROMPT
from mini_agent.tools import TOOL_SCHEMAS, run_todo_write
from mini_agent.tool_registry import TOOL_HANDLERS
from mini_agent.subagent import TASK_TOOL, run_subagent
from mini_agent.skill_loader import SkillLoader, LOAD_SKILL_TOOL
from mini_agent.todo import TodoManager
from mini_agent.terminal_output import TerminalOutput


HELP_TEXT = (
    "直接输入问题并按回车发送，可以接着上一轮继续提问。\n"
    "/help  查看帮助\n"
    "/new   开始新会话，清空聊天历史和任务清单\n"
    "/exit  退出程序\n"
    "等待输入时 Ctrl+C 退出；执行时 Ctrl+C 中断本次任务。"
)


def run_chat(llm, system_prompt, tool_schemas, tool_handlers, todo_manager):
    """外层等用户输入；内层 agent_loop 负责完成一次任务。"""
    # 放在循环外，普通追问保留之前的模型回答和工具结果。
    messages = [{"role": "system", "content": system_prompt}]
    print("MiniAgent 连续对话已启动。")
    print(HELP_TEXT)

    while True:
        try:
            query = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出 MiniAgent。")
            break

        if not query:
            continue

        command = query.lower()
        if command in {"/exit", "exit", "quit", "q"}:
            print("已退出 MiniAgent。")
            break
        if command == "/help":
            print(HELP_TEXT)
            continue
        if command == "/new":
            # 保留系统提示词；原地重置列表和清单，不遗留旧任务状态。
            messages[:] = [{"role": "system", "content": system_prompt}]
            todo_manager.update([])
            print("已开始新会话，聊天历史和任务清单已清空，项目文件保持不变。")
            continue
        if command.startswith("/"):
            print("未知命令，输入 /help 查看帮助。")
            continue

        messages.append({"role": "user", "content": query})
        output = TerminalOutput()
        try:
            trigger_hooks("UserPromptSubmit", query)
            answer = agent_loop(
                llm, messages,
                tool_schemas=tool_schemas,
                tool_handlers=tool_handlers,
                output=output,
            )
        except (Exception, KeyboardInterrupt) as error:
            # 内层已补齐未返回的工具结果；这里只记录本次停止的原因。
            if isinstance(error, KeyboardInterrupt):
                reason = "用户中断"
            elif isinstance(error, EOFError):
                reason = "输入已结束"
            else:
                reason = f"发生异常（{type(error).__name__}）"
                print(f"[异常详情] {error}")
            notice = (
                f"本次任务因{reason}停止，尚未正常完成。"
                "已执行的操作未自动撤销；结果未确认的操作应先核实状态再重试。"
            )
            messages.append({"role": "user", "content": f"<运行状态>{notice}</运行状态>"})
            print(f"[任务停止] {notice}")
            if isinstance(error, EOFError):
                print("已退出 MiniAgent。")
                break
            print("可以继续输入问题，或用 /new 开始新会话。")
            continue

        # agent_loop 已经保存模型回答，这里只展示，不再次追加。
        output.finish(answer)


def main():
    # settings：配置对象；llm：使用这些配置创建的模型客户端。
    settings = Settings.from_env()
    llm = LLMClient(settings)
    skill_loader = SkillLoader(Path("skills"))
    # 任务清单绑定当前会话，不使用基础工具中的全局默认清单。
    todo_manager = TodoManager()

    def run_task(prompt: str) -> str:
        """模型只提供任务描述，程序负责传入当前客户端。"""
        return run_subagent(llm, prompt)

    # 创建父 Agent 专用配置，保留原来的基础配置。
    parent_tools = [
        *TOOL_SCHEMAS,
        TASK_TOOL,
        LOAD_SKILL_TOOL,
    ]

    parent_handlers = {
        **TOOL_HANDLERS,
        "todo_write": partial(run_todo_write, manager=todo_manager),
        "task": run_task,
        "load_skill": skill_loader.load,
    }

    # 只加入目录，不加入技能全文。
    system_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"可用技能：\n{skill_loader.catalog()}\n\n"
        "当任务符合某项技能的适用场景时，"
        "先调用 load_skill 获取完整说明，再开展工作。"
        "无关任务无需加载技能。"
    )
    run_chat(llm, system_prompt, parent_tools, parent_handlers, todo_manager)


if __name__ == "__main__":
    # 直接运行本文件时启动；被其他模块导入时不自动启动。
    main()
