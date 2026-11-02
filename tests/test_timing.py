"""耗时统计测试：使用可控时钟，不等待、不调用真实模型。"""

import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessage

from mini_agent import agent
from mini_agent.subagent import run_subagent, TASK_TOOL


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        clock = patch.object(agent, "perf_counter", side_effect=lambda: self.now,
                             create=True)
        clock.start()
        self.addCleanup(clock.stop)

    def client(self, responses, seconds):
        sequence = iter(zip(responses, seconds))

        def chat(messages, schemas):
            response, duration = next(sequence)
            self.now += duration
            return SimpleNamespace(choices=[SimpleNamespace(message=response)])

        return SimpleNamespace(chat=chat)

    def request(self, name, arguments):
        return ChatCompletionMessage(role="assistant", tool_calls=[{
            "id": "call_time", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }])

    def test_final_log_counts_model_time(self):
        llm = self.client([ChatCompletionMessage(role="assistant", content="完成")], [2.5])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(agent.agent_loop(llm, []), "完成")
        log = output.getvalue()
        self.assertEqual(log.count("[结束日志]"), 1)
        self.assertIn("总耗时：2.50 秒", log)
        self.assertIn("模型请求：1 次 / 2.50 秒", log)

    def test_approval_wait_is_separate_from_tool_time(self):
        llm = self.client([
            self.request("cmd", {"command": "del practice/demo.txt"}),
            ChatCompletionMessage(role="assistant", content="已拒绝"),
        ], [1, 1])

        def reject(_):
            self.now += 4
            return "n"

        handler = Mock()
        output = io.StringIO()
        with patch("builtins.input", side_effect=reject), contextlib.redirect_stdout(output):
            agent.agent_loop(llm, [], tool_handlers={"cmd": handler})
        handler.assert_not_called()
        log = output.getvalue()
        self.assertIn("总耗时：6.00 秒", log)
        self.assertIn("执行前检查：4.00 秒", log)
        self.assertIn("工具执行：0.00 秒", log)

    def test_limit_still_prints_elapsed_time(self):
        llm = self.client([self.request("cmd", {"command": "echo test"})], [2])

        def execute(**arguments):
            self.now += 1
            return "结果"

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            answer = agent.agent_loop(llm, [], tool_handlers={"cmd": execute}, max_turns=1)
        self.assertIn("1 轮上限", answer)
        self.assertIn("总耗时：3.00 秒", output.getvalue())
        self.assertIn("退出原因：轮次上限", output.getvalue())

    def test_exception_is_preserved_and_logged(self):
        def chat(*args):
            self.now += 3
            raise RuntimeError("模拟请求失败")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, "模拟请求失败"):
                agent.agent_loop(SimpleNamespace(chat=chat), [])
        self.assertIn("总耗时：3.00 秒", output.getvalue())
        self.assertIn("退出原因：异常", output.getvalue())

    def test_parent_includes_child_time_without_merging_counters(self):
        llm = self.client([
            self.request("task", {"prompt": "子任务"}),
            ChatCompletionMessage(role="assistant", content="子结论"),
            ChatCompletionMessage(role="assistant", content="父结论"),
        ], [1, 3, 2])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            answer = agent.agent_loop(
                llm, [], tool_schemas=[TASK_TOOL],
                tool_handlers={"task": lambda prompt: run_subagent(llm, prompt)},
            )
        self.assertEqual(answer, "父结论")
        summaries = [line for line in output.getvalue().splitlines() if "[结束日志]" in line]
        self.assertEqual(len(summaries), 2)
        child, parent = summaries
        self.assertIn("子 Agent", child)
        self.assertIn("总耗时：3.00 秒", child)
        self.assertIn("总耗时：6.00 秒", parent)
        self.assertIn("模型请求：2 次 / 3.00 秒", parent)
        self.assertIn("工具执行：3.00 秒", parent)


if __name__ == "__main__":
    unittest.main()
