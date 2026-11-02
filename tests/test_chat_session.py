"""连续对话与失败恢复：用模拟模型检查，不请求真实 API。"""

import contextlib
from copy import deepcopy
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessage

import main
from mini_agent.agent import agent_loop
from mini_agent.todo import TodoManager


def response(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class ChatSessionTests(unittest.TestCase):
    def run_chat(self, inputs, outputs, todo=None):
        """只替代输入和模型边界，实际运行外层与内层循环。"""
        history = []
        sequence = iter(outputs)

        def chat(messages, schemas):
            history.append(deepcopy(messages))
            item = next(sequence)
            if isinstance(item, BaseException):
                raise item
            return response(ChatCompletionMessage(role="assistant", content=item))

        output = io.StringIO()
        with patch("builtins.input", side_effect=inputs), contextlib.redirect_stdout(output):
            runner = getattr(main, "run_chat", None)
            self.assertTrue(callable(runner), "尚未实现连续对话入口 run_chat")
            runner(SimpleNamespace(chat=chat), "系统说明", [], {}, todo or TodoManager())
        return history, output.getvalue()

    def test_followup_keeps_history_without_duplicate_answer(self):
        history, output = self.run_chat(
            ["什么是 Agent？", "它有什么用？", "/exit"], ["第一份回答", "第二份回答"],
        )
        self.assertEqual([m["role"] for m in history[1]],
                         ["system", "user", "assistant", "user"])
        self.assertEqual(history[1][2]["content"], "第一份回答")
        self.assertEqual(output.count("模型输出 > 第一份回答"), 1)

    def test_blank_and_commands_do_not_request_model(self):
        history, output = self.run_chat(["  ", "/help", "/unknown", "/exit"], [])
        self.assertEqual(history, [])
        self.assertIn("/new", output)
        self.assertIn("未知命令", output)

    def test_new_clears_history_and_todo_but_keeps_system(self):
        todo = TodoManager()
        todo.update([{"content": "旧计划", "status": "pending"}])
        history, _ = self.run_chat(["旧问题", "/new", "新问题", "/exit"],
                                   ["旧回答", "新回答"], todo)
        self.assertEqual(history[1], [
            {"role": "system", "content": "系统说明"},
            {"role": "user", "content": "新问题"},
        ])
        self.assertEqual(todo.items, [])

    def test_followup_does_not_clear_todo(self):
        todo = TodoManager()
        todo.update([{"content": "继续处理", "status": "in_progress"}])
        self.run_chat(["继续", "再继续", "/exit"], ["好的", "完成"], todo)
        self.assertEqual(todo.items[0]["content"], "继续处理")

    def test_model_failure_and_interrupt_return_to_input(self):
        for error in (RuntimeError("模拟请求失败"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                history, output = self.run_chat(["第一次", "继续", "/exit"], [error, "恢复回答"])
                self.assertEqual(history[-1][-1]["content"], "继续")
                self.assertIn("第一次", str(history[-1]))
                self.assertIn("恢复回答", output)
                self.assertIn("未自动撤销", output)

    def test_eof_and_idle_interrupt_exit_without_model_call(self):
        for error in (EOFError(), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                history, _ = self.run_chat([error], [])
                self.assertEqual(history, [])


class ToolBatchRecoveryTests(unittest.TestCase):
    def test_failure_fills_entire_batch_without_repeating_completed_tool(self):
        for error in (RuntimeError("执行失败"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                request = ChatCompletionMessage(role="assistant", tool_calls=[
                    {"id": name, "type": "function",
                     "function": {"name": name, "arguments": "{}"}}
                    for name in ("first", "second", "third")
                ])
                llm = Mock()
                llm.chat.return_value = response(request)
                handlers = {
                    "first": Mock(return_value="已经成功写入"),
                    "second": Mock(side_effect=error),
                    "third": Mock(),
                }
                schemas = [{"type": "function", "function": {"name": name}}
                           for name in handlers]
                messages = [{"role": "user", "content": "执行三个步骤"}]
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(type(error)):
                        agent_loop(llm, messages, schemas, handlers)
                results = [m for m in messages if m["role"] == "tool"]
                self.assertEqual([m["tool_call_id"] for m in results],
                                 ["first", "second", "third"])
                self.assertEqual(results[0]["content"], "已经成功写入")
                self.assertIn("未确认", results[1]["content"])
                self.assertIn("未执行", results[2]["content"])
                handlers["first"].assert_called_once()
                handlers["third"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
