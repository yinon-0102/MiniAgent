"""工具实现及模型可见的工具说明；执行函数由 tool_registry 注册。"""

import glob
import os
import subprocess

from pathlib import Path
from mini_agent.todo import TodoManager

# WORKDIR：程序启动时的工作目录；resolve 转为解析后的绝对路径。
WORKDIR = Path.cwd().resolve()
# 当前程序使用的任务清单管理器，多次调用工具时复用。
TODO = TodoManager()


def run_cmd(command: str) -> str:
    """command 是待执行的 Windows 命令；返回输出、错误或超时信息。"""
    # 教材式的简单关键字检查，不等同于命令沙箱。
    # dangerous：工具内部保留的禁止项；any 表示至少一项匹配就拒绝。
    dangerous = ["shutdown", "reboot", "format ", "diskpart", "rd /s", "rmdir /s", "del /s"]
    if any(word in command.lower() for word in dangerous):
        return "Error: Dangerous command blocked"

    try:
        # result：子进程运行结果；subprocess.run 等待命令结束后返回。
        result = subprocess.run(
            command,
            shell=True,  # 通过命令解释器执行，支持管道、重定向等语法。
            # COMSPEC 是 Windows 命令解释器路径，未设置时使用 cmd.exe。
            executable=os.environ.get("COMSPEC", "cmd.exe"),
            cwd=os.getcwd(),  # 命令的起始目录，不会限制其全部访问范围。
            capture_output=True,  # 捕获标准输出和标准错误，方便交给模型。
            text=True,  # 将输出作为字符串读取。
            errors="replace",  # 无法解码的字符使用替代字符，避免解码中断。
            timeout=120,  # 最多等待 120 秒。
        )
        # stdout 是标准输出，stderr 是错误输出；合并后去除首尾空白。
        output = (result.stdout + result.stderr).strip()
        # 限制返回长度，避免过多输出占用模型上下文。
        return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except OSError as exc:
        return f"Error: {exc}"


def safe_path(p: str) -> Path:
    """p 是传入的路径；返回工作目录内的路径对象，越界则抛出异常。"""
    # 组合工作目录与传入路径，并解析 .. 等路径成分。
    path = (WORKDIR / p).resolve()

    # is_relative_to 检查解析后的路径是否位于工作目录内。
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")

    return path


def run_read(path: str, limit: int | None = None) -> str:
    """读取 path 对应的文件；limit 限制返回行数，None 表示不限制。"""
    try:
        # file_path 是检查后的路径对象，text 是实际读取的文本。
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")

        if limit is not None:
            if limit <= 0:
                raise ValueError("limit 必须大于 0")

            # splitlines 拆成各行，切片保留前 limit 行，再用换行符拼接。
            text = "\n".join(text.splitlines()[:limit])

        return text
    except (OSError, UnicodeError, ValueError) as exc:
        return f"Error: {exc}"


def run_write(path: str, content: str) -> str:
    """将 content 写入 path；文件不存在时创建，存在时覆盖。"""
    try:
        file_path = safe_path(path)

        # parent 是父目录；递归创建缺失的目录，已有目录不报错。
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        return f"Wrote file: {path}"
    except (OSError, UnicodeError, ValueError) as exc:
        return f"Error: {exc}"



def run_edit(path: str, old_text: str, new_text: str) -> str:
    """把文件中第一处 old_text 原文替换为 new_text 新文本。"""
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")

        # 原文为空或不存在时直接返回错误，不修改文件。
        if not old_text:
            return "Error: old_text must not be empty"
        if old_text not in text:
            return f"Error: text not found in {path}"

        # replace 的第三个参数 1 表示只替换第一处匹配。
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited file: {path}"
    except (OSError, UnicodeError, ValueError) as exc:
        return f"Error: {exc}"


def run_glob(pattern: str) -> str:
    """按 pattern 路径模式查找，例如 *.txt 或 **/*.py；返回匹配路径。"""
    try:
        # 在开始查找前拒绝明显越出工作目录的模式。
        safe_path(pattern)
        # matches：查找到的路径；集合去重，sorted 排序，过滤越界结果。
        # root_dir 指定查找根目录；recursive=True 支持 ** 匹配多层目录。
        matches = sorted({
            match
            for match in glob.glob(pattern, root_dir=WORKDIR, recursive=True)
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR)
        })
        shown = matches[:200]  # 实际展示的路径，最多 200 项。
        if len(matches) > 200:
            shown.append("... (more matches omitted; narrow the pattern)")
        return "\n".join(shown) if shown else "(no matches)"
    except (OSError, ValueError) as exc:
        return f"Error: {exc}"


def run_todo_write(todos: list, *, manager: TodoManager | None = None) -> str:
    """更新指定会话的清单；未传管理器时保留原来的默认行为。"""
    if manager is None:
        manager = TODO
    try:
        output = manager.update(todos)
    except ValueError as error:
        # 将参数错误转换成工具结果，供模型根据错误重新提交。
        return f"任务清单更新失败：{error}"

    print(f"\n[当前计划]\n{output}")
    return output



# TOOL_SCHEMAS：发给模型的工具说明，与实际执行函数分开维护。
# name 是工具名称，description 是用途，parameters 描述参数结构。
# properties 列出参数，required 指定必填项，additionalProperties=False 禁止额外参数。
TOOL_SCHEMAS = [
{
    "type": "function",
    "function": {
        "name": "cmd",  # 对应分发表中的 cmd，参数为 command 命令字符串。
        "description": "通过 Windows cmd.exe 执行终端命令，返回标准输出和错误输出。使用 cmd 语法，例如 dir /b，不要使用 Bash 或 PowerShell 语法。",
        "parameters": {
            "type": "object",
            "properties": {
            "command": {
                "type": "string",
                "description": "需要执行的 cmd.exe 命令。",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "read_file",  # 参数为 path 文件路径，以及可选的 limit 行数。
        "description": "读取工作目录内的 UTF-8 文本文件，可限制返回行数。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于工作目录的文件路径。",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "最多返回的行数，不传则返回全文。",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "write_file",  # 参数为 path 文件路径和 content 完整写入内容。
        "description": "向工作目录内的文件写入 UTF-8 文本。自动创建父目录，文件已存在时覆盖原有内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于工作目录的目标文件路径。",
                },
                "content": {
                    "type": "string",
                    "description": "需要写入文件的完整文本内容。",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "edit_file",  # 参数为 path 路径、old_text 原文、new_text 新文本。
        "description": "修改工作目录内的 UTF-8 文本文件，只替换第一处精确匹配的原文。原文不存在时返回错误。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于工作目录的文件路径。",
                },
                "old_text": {
                    "type": "string",
                    "minLength": 1,
                    "description": "需要替换的原文，必须与文件内容精确匹配。",
                },
                "new_text": {
                    "type": "string",
                    "description": "替换后的文本，可以为空字符串。",
                },
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "glob",  # 参数为 pattern 路径匹配模式。
        "description": "按文件名模式查找工作目录内的文件或目录，例如 practice/*.txt 或 **/*.py。最多返回 200 个匹配路径。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "相对于工作目录的匹配模式，** 可匹配多层目录。",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "todo_write",
        "description": (
            "创建或更新当前任务的计划清单。"
            "每次提交更新后的完整清单，会替换旧清单。"
            "多步骤任务开始前制定计划，执行过程中更新状态。"
            "同一时间最多一项任务处于进行中。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "更新后的完整任务清单，空列表表示清空。",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "minLength": 1,
                                "description": "具体的任务内容。",
                            },
                            "status": {
                                "type": "string",
                                "enum": [
                                    "pending",
                                    "in_progress",
                                    "completed",
                                ],
                                "description": "待处理、进行中或已完成。",
                            },
                        },
                        "required": ["content", "status"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["todos"],
            "additionalProperties": False,
        },
    },
},
]
