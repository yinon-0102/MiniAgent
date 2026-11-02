"""流式协议测试：模拟 SDK 分片，不访问模型服务。"""

import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionChunk

from mini_agent.config import Settings
from mini_agent.llm_client import LLMClient
from mini_agent.agent import agent_loop
from mini_agent.todo import TodoManager
import main


def chunk(delta=None, finish=None, usage=None):
    return ChatCompletionChunk(
        id="test", object="chat.completion.chunk", created=0, model="test",
        choices=[] if usage else [{"index": 0, "delta": delta or {},
                                   "finish_reason": finish}],
        usage=usage,
    )


class Stream:
    def __init__(self, items):
        self.items = items
        self.closed = False

    def __iter__(self):
        for item in self.items:
            if isinstance(item, BaseException):
                raise item
            yield item

    def close(self):
        self.closed = True


class StreamingTests(unittest.TestCase):
    def client(self, items, stream=True):
        client = LLMClient.__new__(LLMClient)
        client.settings = Settings("unused", "http://localhost", "test", 0, stream, 60)
        result = Stream(items)
        client.client = Mock()
        client.client.chat.completions.create.return_value = result
        return client, result

    def test_text_arrives_before_next_chunk_and_usage_is_preserved(self):
        received = []

        class CheckedStream(Stream):
            def __iter__(self):
                yield chunk({"content": "你好"})
                self_test.assertEqual(received, ["你好"])
                yield chunk({"content": "世界"})
                yield chunk(finish="stop")
                yield chunk(usage={"prompt_tokens": 12, "completion_tokens": 3,
                                   "total_tokens": 15})

        self_test = self
        client, _ = self.client([])
        stream = CheckedStream([])
        client.client.chat.completions.create.return_value = stream
        response = client.chat([], [], on_text=received.append)
        self.assertEqual(response.choices[0].message.content, "你好世界")
        self.assertEqual(response.usage.total_tokens, 15)
        self.assertTrue(stream.closed)
        self.assertTrue(client.client.chat.completions.create.call_args.kwargs["stream"])

    def test_interleaved_tool_arguments_are_assembled_by_index(self):
        client, stream = self.client([
            chunk({"tool_calls": [
                {"index": 1, "id": "b", "type": "function",
                 "function": {"name": "second", "arguments": '{"b":'}},
                {"index": 0, "id": "a", "type": "function",
                 "function": {"name": "first", "arguments": '{"a":'}},
            ]}),
            chunk({"tool_calls": [
                {"index": 0, "function": {"arguments": '1}'}},
                {"index": 1, "function": {"arguments": '2}'}},
            ]}),
            chunk(finish="tool_calls"),
        ])
        message = client.chat([], []).choices[0].message
        self.assertEqual([c.id for c in message.tool_calls], ["a", "b"])
        self.assertEqual([c.function.arguments for c in message.tool_calls],
                         ['{"a":1}', '{"b":2}'])
        self.assertTrue(stream.closed)

    def test_broken_or_truncated_stream_is_rejected_and_closed(self):
        for tail in ([], [chunk(finish="length")], [RuntimeError("断流")],
                     [KeyboardInterrupt()]):
            with self.subTest(tail=tail):
                client, stream = self.client([chunk({"content": "部分文本"}), *tail])
                with self.assertRaises((RuntimeError, KeyboardInterrupt)):
                    client.chat([], [])
                self.assertTrue(stream.closed)
                self.assertEqual(client.client.chat.completions.create.call_count, 1)

    def test_non_streaming_returns_original_response(self):
        client, _ = self.client([], stream=False)
        response = SimpleNamespace(choices=[])
        client.client.chat.completions.create.return_value = response
        self.assertIs(client.chat([], []), response)
        self.assertFalse(client.client.chat.completions.create.call_args.kwargs["stream"])

    def test_tool_executes_only_after_stream_closes_then_final_is_displayed_once(self):
        handler = Mock(return_value="工具结果")
        client, stream = self.client([
            chunk({"content": "先检查"}),
            chunk({"tool_calls": [{"index": 0, "id": "a", "type": "function",
                  "function": {"name": "inspect", "arguments": "{}"}}]}),
            chunk(finish="tool_calls"),
        ])

        def execute():
            self.assertTrue(stream.closed)
            return handler()

        final = Stream([chunk({"content": "**完成**"}), chunk(finish="stop")])
        client.client.chat.completions.create.side_effect = [stream, final]
        target = io.StringIO()
        with patch("builtins.input", side_effect=["执行", "/exit"]), \
                contextlib.redirect_stdout(target):
            main.run_chat(client, "系统", [{"type": "function", "function": {
                "name": "inspect"}}], {"inspect": execute}, TodoManager())
        handler.assert_called_once()
        self.assertEqual(target.getvalue().count("**完成**"), 1)
        self.assertIn("流式", target.getvalue())
        self.assertNotIn("等待完整响应", target.getvalue())

    def test_incomplete_tool_stream_never_executes_or_enters_history(self):
        client, _ = self.client([
            chunk({"tool_calls": [{"index": 0, "id": "a", "type": "function",
                  "function": {"name": "inspect", "arguments": "{}"}}]}),
        ])
        handler = Mock()
        messages = [{"role": "user", "content": "检查"}]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            agent_loop(client, messages, [{"type": "function", "function": {
                "name": "inspect"}}], {"inspect": handler})
        handler.assert_not_called()
        self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main()
