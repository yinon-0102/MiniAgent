"""权限检查：识别禁止的命令，以及需要用户确认的操作。"""

import re  # 正则表达式模块，用于识别命令中的特定格式。


# 硬拒绝列表：命令包含这些字符串时，直接禁止。
DENY_LIST = [
    "shutdown",  # 关机命令
    "reboot",  # 重启命令
    "format ",  # 格式化命令
    "diskpart",  # 磁盘分区工具
    "rd /s",  # 递归删除目录
    "rmdir /s",  # 递归删除目录，rd 的另一种写法
    "del /s",  # 递归删除文件
]


# 删除命令的匹配规则；compile 将规则预先编译，供后续重复使用。
# 匹配命令开头或分隔符后的 del、erase、rd、rmdir，避免把 echo del 当作删除。
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?:^|[&|()\n])\s*@?(?:del|erase|rd|rmdir)(?=\s|$|[&|()])",
    re.IGNORECASE,  # 忽略大小写，例如 DEL 和 del 都能匹配。
)


# 审批规则列表：命中表示需要询问用户，不是直接禁止。
PERMISSION_RULES = [
    {
        "tools": ["cmd"],  # 本条规则适用的工具名称。
        # check 保存检查函数；lambda 是匿名函数，args 是工具参数字典。
        "check": lambda args: contains_destructive_command(
            args.get("command", "")  # 取出命令；没有这个键时使用空字符串。
        ),
        "message": "该命令可能删除文件或目录，需要用户确认",  # 审批原因。
    },
]


def check_deny_list(command: str) -> str | None:
    """检查命令 command；命中返回拒绝原因，否则返回 None。"""
    # normalized_command：转换为小写的命令，统一处理大小写。
    normalized_command = command.lower()

    # pattern：当前遍历到的禁止字符串。
    for pattern in DENY_LIST:
        if pattern in normalized_command:
            return f"操作被禁止：命令包含禁止项”{pattern}“"

    return None  # 仅表示没有命中硬拒绝项，不代表已通过全部权限检查。


def contains_destructive_command(command: str) -> bool:
    """判断命令是否匹配删除规则：匹配返回 True，否则返回 False。"""
    # search 查找匹配；bool 将“匹配结果或 None”转换为布尔值。
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))


def check_rules(tool_name: str, arguments: dict) -> str | None:
    """tool_name 是工具名称，arguments 是参数；命中返回审批原因，否则返回 None。"""
    # rule：当前遍历到的一条审批规则。
    for rule in PERMISSION_RULES:
        # 先检查本条规则是否适用于当前工具。
        if tool_name in rule["tools"]:
            # 取出检查函数并传入参数；返回 True 表示命中规则。
            if rule["check"](arguments):
                return rule["message"]

    return None  # 没有命中需要用户确认的规则。


def ask_user(tool_name: str, arguments: dict, reason: str) -> bool:
    """展示审批信息；用户明确同意返回 True，否则返回 False。"""
    print(f"\n需要用户确认：{reason}")
    print(f"工具名称：{tool_name}")
    print(f"调用参数：{arguments}")

    try:
        # choice：用户输入的审批决定。
        choice = input(
            "是否允许本次操作？输入 “y” 允许，输入回车拒绝："
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        # 无法读取输入或用户按 Ctrl+C 时，按拒绝处理。
        print("\n未获得确认，已拒绝本次操作。")
        return False

    return choice == "y"


def check_permission(tool_name: str, arguments: dict) -> bool:
    """统一检查权限：允许返回 True，拒绝返回 False。"""

    # 第一道闸门：命令命中硬拒绝项，立即拒绝。
    if tool_name == "cmd":
        command = arguments.get("command", "")
        reason = check_deny_list(command)

        if reason is not None:
            print(reason)
            return False

    # 第二道闸门：检查是否存在需要用户确认的原因。
    reason = check_rules(tool_name, arguments)

    # 第三道闸门：有审批原因时，由用户决定。
    if reason is not None:
        return ask_user(tool_name, arguments, reason)

    # 未命中硬拒绝项和审批规则，允许执行。
    return True