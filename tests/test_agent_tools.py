"""工具配置测试：使用模拟模型检查独立工具集合，不发送 API 请求。"""

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from openai.types.chat import ChatCompletionMessage

from mini_agent.agent import agent_loop


class AgentToolConfigTests(unittest.TestCase):
    def make_client(self, *messages):
        llm = Mock()
        llm.chat.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=message)])
            for message in messages
        ]
        return llm

    def request(self, name):
        return ChatCompletionMessage(role="assistant", tool_calls=[{
            "id": "call_config",
            "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }])

    def test_custom_tools_execute_without_todo_reminders(self):
        schemas = [{"type": "function", "function": {
            "name": "inspect", "description": "测试工具",
            "parameters": {"type": "object", "properties": {}},
        }}]
        handler = Mock(return_value="检查结果")
        llm = self.make_client(
            *(self.request("inspect") for _ in range(3)),
            ChatCompletionMessage(role="assistant", content="完成"),
        )
        history = [{"role": "user", "content": "检查"}]
        with contextlib.redirect_stdout(io.StringIO()):
            answer = agent_loop(llm, history, schemas, {"inspect": handler})
        self.assertEqual(answer, "完成")
        self.assertEqual(handler.call_count, 3)
        for call in llm.chat.call_args_list:
            self.assertIs(call.args[1], schemas)
        self.assertEqual([m["content"] for m in history if m["role"] == "tool"],
                         ["检查结果"] * 3)
        self.assertFalse(any("<reminder>" in m.get("content", "") for m in history))

    def test_empty_schema_list_is_preserved(self):
        llm = self.make_client(ChatCompletionMessage(role="assistant", content="你好"))
        schemas = []
        with contextlib.redirect_stdout(io.StringIO()):
            answer = agent_loop(llm, [], schemas, {})
        self.assertEqual(answer, "你好")
        self.assertIs(llm.chat.call_args.args[1], schemas)

    def test_hidden_tool_is_rejected_even_if_handler_exists(self):
        handler = Mock()
        llm = self.make_client(self.request("write_file"))
        with self.assertRaisesRegex(ValueError, "当前 Agent 不允许使用工具"):
            agent_loop(llm, [], [], {"write_file": handler})
        handler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
