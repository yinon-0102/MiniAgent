"""文件工具测试：使用临时目录和模拟模型，验证真实文件操作与结果回填。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessage

from mini_agent import tools
from mini_agent.agent import agent_loop
from mini_agent.tool_registry import TOOL_HANDLERS


class FileToolTests(unittest.TestCase):
    """检查读取、写入、编辑、查找及路径限制。"""

    def setUp(self):
        """每个测试开始前，创建独立临时目录并替换工具的工作目录。"""
        # temp 是临时目录管理对象，root 是它解析后的绝对路径。
        self.temp = tempfile.TemporaryDirectory(
            prefix="s02-", dir=Path(__file__).resolve().parent
        )
        self.addCleanup(self.temp.cleanup)  # 测试结束后自动清理临时目录。
        self.root = Path(self.temp.name).resolve()
        # patch 临时替换 WORKDIR；结束时恢复，避免影响项目文件。
        self.workspace = patch.object(tools, "WORKDIR", self.root)
        self.workspace.start()
        self.addCleanup(self.workspace.stop)

    def tool(self, name):
        """按 name 从工具模块获取函数，确认函数存在且可以调用。"""
        handler = getattr(tools, name, None)
        self.assertTrue(callable(handler), f"Missing tool: {name}")
        return handler

    def test_edit_replaces_only_first_match_and_keeps_other_text(self):
        """编辑只替换第一次匹配，并保留中文和其他文本。"""
        tools.run_write("nested/demo.txt", "你好 Agent\nrepeat repeat")
        result = self.tool("run_edit")("nested/demo.txt", "repeat", "done")
        self.assertFalse(result.startswith("Error:"))
        self.assertEqual(
            tools.run_read("nested/demo.txt"), "你好 Agent\ndone repeat"
        )

    def test_failed_edit_leaves_file_unchanged(self):
        """原文不存在或为空时返回错误，文件内容保持原样。"""
        tools.run_write("demo.txt", "keep this")
        edit = self.tool("run_edit")
        self.assertTrue(edit("demo.txt", "missing", "new").startswith("Error:"))
        self.assertTrue(edit("demo.txt", "", "new").startswith("Error:"))
        self.assertEqual(tools.run_read("demo.txt"), "keep this")

    def test_file_tools_reject_paths_outside_workspace(self):
        """检查文件工具是否拒绝超出工作目录的路径。"""
        edit = self.tool("run_edit")
        find = self.tool("run_glob")
        results = [
            tools.run_read("../outside.txt"),
            tools.run_write("../outside.txt", "must not be written"),
            edit("../outside.txt", "old", "new"),
            find("../*.txt"),
        ]
        for result in results:
            self.assertTrue(result.startswith("Error:"), result)

    def test_glob_finds_nested_matches_and_handles_no_matches(self):
        """查找多层目录中的匹配文件，并检查无匹配时的返回值。"""
        tools.run_write("nested/b.txt", "b")
        tools.run_write("a.txt", "a")
        tools.run_write("nested/ignore.py", "pass")
        find = self.tool("run_glob")
        matches = find("**/*.txt").replace("\\", "/").splitlines()
        self.assertEqual(set(matches), {"a.txt", "nested/b.txt"})
        self.assertEqual(find("**/*.missing"), "(no matches)")

    def test_glob_limits_results(self):
        """创建 201 个匹配文件，检查只返回 200 个路径和一条截断提示。"""
        for index in range(201):
            (self.root / f"{index:03d}.txt").touch()
        result = self.tool("run_glob")("*.txt").splitlines()
        self.assertEqual(len(result), 201)
        self.assertTrue(result[-1].startswith("..."))

    def test_all_schemas_have_matching_registered_handlers(self):
        """检查模型可见的工具名称与分发表一致，没有缺失或重复。"""
        expected = {
            "cmd",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "todo_write",
        }
        names = [schema["function"]["name"] for schema in tools.TOOL_SCHEMAS]
        self.assertEqual(set(names), expected)
        self.assertEqual(len(names), len(expected))
        self.assertEqual(set(TOOL_HANDLERS), expected)

    def test_write_edit_read_and_glob_results_return_to_model(self):
        """模拟多轮模型请求，实际执行写入、编辑、读取和查找。"""
        # requests：按执行顺序排列的工具名称和参数字典。
        requests = [
            ("write_file", {"path": "demo.txt", "content": "Hello Agent"}),
            ("edit_file", {"path": "demo.txt", "old_text": "Hello", "new_text": "你好"}),
            ("read_file", {"path": "demo.txt"}),
            ("glob", {"pattern": "*.txt"}),
        ]
        self.assertTrue(all(name in TOOL_HANDLERS for name, _ in requests))
        # model_messages：模拟模型每轮提出的工具调用消息。
        model_messages = [
            ChatCompletionMessage(
                role="assistant",
                tool_calls=[{
                    "id": f"call_{index}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }],
            )
            for index, (name, arguments) in enumerate(requests)
        ]
        model_messages.append(ChatCompletionMessage(role="assistant", content="已完成。"))
        # 不访问真实模型；每次请求依次返回预先准备好的响应。
        llm = Mock()
        llm.chat.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=message)])
            for message in model_messages
        ]
        history = [{"role": "user", "content": "创建、修改、读取并查找测试文件。"}]

        with contextlib.redirect_stdout(io.StringIO()):
            answer = agent_loop(llm, history)

        # results：从对话记录中筛选出的工具结果，按调用 ID 检查回填。
        results = [message for message in history if message["role"] == "tool"]
        self.assertEqual(answer, "已完成。")
        self.assertEqual(llm.chat.call_count, 5)
        self.assertEqual([item["tool_call_id"] for item in results],
                         [f"call_{index}" for index in range(4)])
        self.assertEqual(results[2]["content"], "你好 Agent")
        self.assertEqual(results[3]["content"], "demo.txt")


if __name__ == "__main__":
    unittest.main()
