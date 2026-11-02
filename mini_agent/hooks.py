from mini_agent.permissions import check_permission


"""Hook 机制：登记回调函数，在指定事件发生时依次执行。"""


# 事件名称 → 回调函数列表；同一个事件可以注册多个函数。
HOOKS = {
    "UserPromptSubmit": [],  # 用户提交输入后
    "PreToolUse": [],        # 工具执行前
    "PostToolUse": [],       # 工具执行后
    "Stop": [],              # 循环准备结束时
}


def register_hook(event: str, callback):
    """注册hook"""
    """event 是事件名称，callback 是等待执行的回调函数。"""
    if event not in HOOKS:
        raise ValueError(f"未知的 Hook 事件：{event}")

    # 保存函数对象，此时不执行。
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    """调用hook"""
    """依次调用事件下的回调；遇到非 None 结果时停止并返回。"""
    if event not in HOOKS:
        raise ValueError(f"未知的 Hook 事件：{event}")

    for callback in HOOKS[event]:
        # 将触发事件时携带的参数传给回调函数。
        result = callback(*args)

        if result is not None:
            return result

    return None


def permission_hook(tool_name: str, arguments: dict) -> str | None:
    """将权限检查结果转换为 Hook 的返回值约定。"""
    if check_permission(tool_name, arguments):
        return None  # 允许继续执行其他回调和工具。

    return "权限被拒绝，本次操作未执行。"


def log_hook(tool_name: str, arguments: dict) -> None:
    """记录通过权限检查、即将执行的工具调用。"""
    print(f"[工具调用日志] 工具：{tool_name}，参数：{arguments}")

    return None  # 日志只记录信息，允许继续。


def output_hook(tool_name: str, arguments: dict, output) -> None:
    """工具返回后，记录返回内容的长度。"""
    # output：工具执行函数实际返回的结果。
    output_length = len(str(output))
    print(
        f"[执行后日志] 工具：{tool_name}，"
        f"返回内容长度：{output_length} 个字符"
    )
    return None


def prompt_log_hook(query: str) -> None:
    """用户提交问题后，记录输入的字符数。"""
    print(f"[输入日志] 收到用户问题，共 {len(query)} 个字符。")
    return None


def summary_hook(messages: list) -> str | None:
    """统计当前历史中的工具结果，区别于本次任务的调用次数。"""
    tool_count = 0

    for message in messages:
        if message.get("role") == "tool":
            tool_count += 1

    # 被拒绝的调用也会回填工具结果，因此也计入处理次数。
    # Stop 回调可能要求继续；真正退出时的总耗时由 agent_loop 的 finally 记录。
    print(f"[上下文统计] 当前历史含 {tool_count} 条工具结果（包含之前的任务）。")

    return None  # 允许主循环结束。

# 执行前先检查权限，再记录调用日志；执行后记录返回内容长度。
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", output_hook)
register_hook("UserPromptSubmit", prompt_log_hook)
register_hook("Stop", summary_hook)
