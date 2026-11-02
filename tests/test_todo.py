"""s05 测试：检查清单校验、提醒轮次和精简日志，不请求真实模型。"""

import contextlib
import copy
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessage

from mini_agent import agent, tools
from mini_agent.todo import TodoManager


class TodoTests(unittest.TestCase):
    def test_invalid_update_keeps_previous_list(self):
        manager = TodoManager()
        manager.update([{"content": "旧任务", "status": "pending"}])
        previous = manager.items
        invalid_lists = [
            None,
            [{}] * 21,
            ["错误元素"],
            [{"content": " "}],
            [{"content": "任务", "status": "unknown"}],
            [{"content": str(i), "status": "in_progress"} for i in range(2)],
        ]
        for todos in invalid_lists:
            with self.subTest(todos=todos):
                with self.assertRaises(ValueError):
                    manager.update(todos)
                self.assertIs(manager.items, previous)

    def run_rounds(self, rounds):
        responses = []
        expected_ids = []
        for index, calls in enumerate(rounds):
            tool_calls = []
            for offset, (name, arguments) in enumerate(calls):
                call_id = f"call_{index}_{offset}"
                expected_ids.append(call_id)
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                })
            responses.append(ChatCompletionMessage(role="assistant", tool_calls=tool_calls))
        responses.append(ChatCompletionMessage(role="assistant", content="完成。"))
        iterator = iter(responses)
        snapshots = []

        def chat(history, schemas):
            snapshots.append(copy.deepcopy(history))
            return SimpleNamespace(choices=[SimpleNamespace(message=next(iterator))])

        history = [{"role": "user", "content": "测试任务。"}]
        output = io.StringIO()
        command_handler = Mock(return_value="命令结果")
        with patch.object(tools, "TODO", TodoManager()):
            with patch.dict(agent.TOOL_HANDLERS, {"cmd": command_handler}):
                with contextlib.redirect_stdout(output):
                    answer = agent.agent_loop(SimpleNamespace(chat=chat), history)
        self.assertEqual(answer, "完成。")
        results = [m for m in history if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in results], expected_ids)
        reminders = [m for m in history if m["role"] == "user" and "<reminder>" in m["content"]]
        return reminders, snapshots, output.getvalue(), command_handler

    def test_reminder_counts_rounds_instead_of_individual_calls(self):
        call = ("cmd", {"command": "echo test"})
        reminders, snapshots, _, _ = self.run_rounds([[call] * 3, [call], [call]])
        self.assertEqual(len(reminders), 1)
        self.assertFalse(any("<reminder>" in m.get("content", "") for m in snapshots[2]))
        self.assertEqual(snapshots[3][-1], reminders[0])
        self.assertEqual([m["content"] for m in snapshots[3] if m["role"] == "tool"], ["命令结果"] * 5)

    def test_todo_call_resets_counter_and_plan_is_printed_once(self):
        call = ("cmd", {"command": "echo test"})
        todo_call = ("todo_write", {"todos": [{"content": "唯一清单任务", "status": "pending"}]})
        reminders, snapshots, logs, _ = self.run_rounds([[call], [call], [todo_call], [call], [call], [call]])
        self.assertEqual(len(reminders), 1)
        self.assertFalse(any("<reminder>" in m.get("content", "") for m in snapshots[5]))
        self.assertEqual(snapshots[6][-1], reminders[0])
        self.assertEqual(logs.count("[ ] 唯一清单任务"), 1)
        self.assertNotIn("调用工具：", logs)

    def test_reminder_resets_counter_after_delivery(self):
        call = ("cmd", {"command": "echo test"})
        reminders, _, _, _ = self.run_rounds([[call]] * 6)
        self.assertEqual(len(reminders), 2)

    def test_denial_is_logged_and_never_executes_handler(self):
        reminders, snapshots, logs, handler = self.run_rounds([[('cmd', {'command': 'shutdown /s'})]])
        handler.assert_not_called()
        self.assertEqual(reminders, [])
        self.assertIn("状态：已拒绝", logs)
        self.assertIn("[拒绝原因] 权限被拒绝", logs)
        self.assertIn("权限被拒绝", snapshots[1][-1]["content"])


if __name__ == "__main__":
    unittest.main()
