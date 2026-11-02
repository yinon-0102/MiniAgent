"""s03 权限测试：模拟用户输入和模型响应，不执行删除、关机等命令。"""

import contextlib
import copy
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessage

from mini_agent import agent, permissions


class PermissionTests(unittest.TestCase):
    """检查硬拒绝优先级、审批规则和用户输入处理。"""

    def test_ordinary_command_passes_without_approval(self):
        with patch("builtins.input") as user_input:
            self.assertTrue(
                permissions.check_permission("cmd", {"command": "dir /b"})
            )
        user_input.assert_not_called()

    def test_hard_denial_takes_priority_over_user_approval(self):
        for command in ("SHUTDOWN /s", "del /s practice/*.txt"):
            with self.subTest(command=command):
                with patch("builtins.input", return_value="y") as user_input:
                    with contextlib.redirect_stdout(io.StringIO()):
                        allowed = permissions.check_permission(
                            "cmd", {"command": command}
                        )
                self.assertFalse(allowed)
                user_input.assert_not_called()

    def test_deletion_rule_matches_command_position(self):
        cases = {
            "del practice/demo.txt": True,
            "DEL practice/demo.txt": True,
            "erase practice/demo.txt": True,
            "rmdir practice/demo": True,
            "dir /b & del practice/demo.txt": True,
            "dir /b": False,
            "echo del practice/demo.txt": False,
            "model": False,
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                reason = permissions.check_rules("cmd", {"command": command})
                self.assertEqual(reason is not None, expected)

    def test_user_must_explicitly_approve(self):
        # 当前界面约定只有 y 表示允许；首尾空白和大小写会被统一处理。
        for choice, expected in (("y", True), (" Y ", True), ("", False), ("n", False)):
            with self.subTest(choice=choice):
                with patch("builtins.input", return_value=choice):
                    with contextlib.redirect_stdout(io.StringIO()):
                        allowed = permissions.check_permission(
                            "cmd", {"command": "del practice/demo.txt"}
                        )
                self.assertEqual(allowed, expected)

    def test_missing_or_interrupted_input_is_denied(self):
        for exception in (EOFError, KeyboardInterrupt):
            with self.subTest(exception=exception.__name__):
                with patch("builtins.input", side_effect=exception):
                    with contextlib.redirect_stdout(io.StringIO()):
                        allowed = permissions.check_permission(
                            "cmd", {"command": "del practice/demo.txt"}
                        )
                self.assertFalse(allowed)


class PermissionLoopTests(unittest.TestCase):
    """使用真实权限检查和模拟工具，检查权限决定与消息回填。"""

    def run_loop(self, commands, user_choice=""):
        # 构造模型一次提出的全部调用，并为每次调用分配独立 ID。
        tool_calls = [
            {
                "id": f"call_permission_{index}",
                "type": "function",
                "function": {
                    "name": "cmd",
                    "arguments": json.dumps({"command": command}),
                },
            }
            for index, command in enumerate(commands)
        ]
        first_message = ChatCompletionMessage(role="assistant", tool_calls=tool_calls)
        final_message = ChatCompletionMessage(role="assistant", content="测试完成。")
        model_messages = iter((first_message, final_message))
        snapshots = []

        def chat(history, schemas):
            # 保存请求当时的对话快照，确认第二轮模型真正能看到工具结果。
            snapshots.append(copy.deepcopy(history))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=next(model_messages))]
            )

        llm = Mock()
        llm.chat.side_effect = chat
        handler = Mock(return_value="模拟工具已执行。")
        history = [{"role": "user", "content": "测试权限流程。"}]

        # 替换执行函数，因此测试中的删除或禁止命令都不会实际执行。
        with patch.dict(agent.TOOL_HANDLERS, {"cmd": handler}):
            with patch("builtins.input", return_value=user_choice) as user_input:
                with contextlib.redirect_stdout(io.StringIO()):
                    answer = agent.agent_loop(llm, history)

        self.assertEqual(answer, "测试完成。")
        self.assertEqual(llm.chat.call_count, 2)
        results = [message for message in snapshots[1] if message["role"] == "tool"]
        self.assertEqual(len(results), len(commands))
        self.assertEqual(
            [result["tool_call_id"] for result in results],
            [call["id"] for call in tool_calls],
        )
        return handler, user_input, results

    def test_rejected_call_is_not_executed_and_denial_reaches_model(self):
        handler, user_input, results = self.run_loop(["del practice/demo.txt"])
        handler.assert_not_called()
        user_input.assert_called_once()
        self.assertIn("权限被拒绝", results[0]["content"])

    def test_approved_call_is_executed_once(self):
        handler, user_input, results = self.run_loop(
            ["del practice/demo.txt"], user_choice="Y"
        )
        handler.assert_called_once_with(command="del practice/demo.txt")
        user_input.assert_called_once()
        self.assertEqual(results[0]["content"], "模拟工具已执行。")

    def test_hard_denial_never_executes_or_requests_approval(self):
        handler, user_input, results = self.run_loop(["shutdown /s"], user_choice="y")
        handler.assert_not_called()
        user_input.assert_not_called()
        self.assertIn("权限被拒绝", results[0]["content"])

    def test_denial_does_not_skip_other_calls_in_same_response(self):
        handler, user_input, results = self.run_loop(
            ["del practice/demo.txt", "echo permission-test"]
        )
        handler.assert_called_once_with(command="echo permission-test")
        user_input.assert_called_once()
        self.assertIn("权限被拒绝", results[0]["content"])
        self.assertEqual(results[1]["content"], "模拟工具已执行。")


if __name__ == "__main__":
    unittest.main()
