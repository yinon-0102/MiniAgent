"""本地命令及结果回填测试：使用模拟模型，不发送真实 API 请求。"""

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from openai.types.chat import ChatCompletionMessage

from mini_agent import tools
from mini_agent.agent import agent_loop


class CmdToolTests(unittest.TestCase):
    """检查命令工具的输出，以及工具结果与调用 ID 的对应关系。"""

    def test_cmd_captures_stdout_and_stderr(self):
        """分别检查标准输出和错误输出能否被工具捕获。"""
        run_cmd = getattr(tools, "run_cmd", None)
        self.assertTrue(callable(run_cmd), "run_cmd 尚未实现")
        self.assertIn("miniagent-stdout", run_cmd("echo miniagent-stdout"))
        self.assertIn("miniagent-stderr", run_cmd("echo miniagent-stderr 1>&2"))

    def test_cmd_result_is_sent_back_to_model(self):
        """模拟一次工具请求和最终回答，验证 Agent 完成两轮请求。"""
        # tool_request：模拟模型提出的工具调用，命令只输出测试文本。
        tool_request = ChatCompletionMessage(
            role="assistant",
            tool_calls=[
                {
                    "id": "call_cmd_test",
                    "type": "function",
                    "function": {
                        "name": "cmd",
                        "arguments": '{"command": "echo miniagent-loop-ok"}',
                    },
                }
            ],
        )
        # final_message：模拟模型读取工具结果后给出的最终回答。
        final_message = ChatCompletionMessage(
            role="assistant", content="命令已执行。"
        )
        # Mock 模拟客户端；side_effect 使每次 chat 按顺序返回不同响应。
        llm = Mock()
        llm.chat.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=message)])
            for message in (tool_request, final_message)
        ]
        messages = [{"role": "user", "content": "请执行测试命令。"}]

        # 临时收集日志，保持测试输出清晰；仍实际执行 echo 命令。
        with contextlib.redirect_stdout(io.StringIO()):
            answer = agent_loop(llm, messages)

        # 断言：检查回答、请求次数、消息顺序和工具结果是否符合预期。
        self.assertEqual(answer, "命令已执行。")
        self.assertEqual(llm.chat.call_count, 2)
        self.assertEqual(
            [message["role"] for message in messages],
            ["user", "assistant", "tool", "assistant"],
        )
        self.assertEqual(messages[2]["tool_call_id"], "call_cmd_test")
        self.assertEqual(messages[2]["content"], "miniagent-loop-ok")
        schema = llm.chat.call_args.args[1][0]["function"]
        self.assertEqual(schema["name"], "cmd")
        self.assertEqual(schema["parameters"]["required"], ["command"])


if __name__ == "__main__":
    unittest.main()
