"""工具分发表：将模型使用的工具名称映射到 Python 执行函数。"""

from mini_agent.tools import run_cmd, run_read, run_write, run_edit, run_glob,run_todo_write


# 左边是工具名称，右边保存函数对象；不加括号，调用时才执行。
TOOL_HANDLERS = {
    "cmd": run_cmd,  # 执行 Windows 命令。
    "read_file": run_read,  # 读取文本文件。
    "write_file": run_write,  # 创建或覆盖文本文件。
    "edit_file": run_edit,  # 替换第一处匹配的原文。
    "glob": run_glob,  # 按路径模式查找文件或目录。
    "todo_write": run_todo_write,  # 更新当前任务清单。
}
