"""终端展示测试：覆盖增量输出、Markdown 与中断清理。"""

import io
import unittest

from rich.console import Console

from mini_agent.terminal_output import TerminalOutput


class TerminalOutputTests(unittest.TestCase):
    def test_redirected_stream_writes_immediately_without_duplicate(self):
        target = io.StringIO()
        output = TerminalOutput(Console(file=target, force_terminal=False))
        with output.response() as write:
            write("你好")
            self.assertIn("你好", target.getvalue())
            write("世界")
        output.finish("你好世界")
        self.assertEqual(target.getvalue().count("你好世界"), 1)
        self.assertNotIn("\x1b", target.getvalue())

    def test_final_answer_is_not_hidden_after_tool_round(self):
        target = io.StringIO()
        output = TerminalOutput(Console(file=target, force_terminal=False))
        with output.response() as write:
            write("先检查文件")
        with output.response():
            pass
        output.finish("没有文本")
        self.assertIn("没有文本", target.getvalue())

    def test_markdown_is_rendered_in_terminal(self):
        target = io.StringIO()
        output = TerminalOutput(Console(file=target, force_terminal=True, width=60,
                                        color_system=None))
        with output.response() as write:
            write("**重点**\n\n```python\nprint('hello')\n```")
        self.assertIn("重点", target.getvalue())
        self.assertIn("hello", target.getvalue())
        self.assertNotIn("**重点**", target.getvalue())

    def test_interrupt_closes_live_before_next_log(self):
        target = io.StringIO()
        console = Console(file=target, force_terminal=True)
        output = TerminalOutput(console)
        with self.assertRaises(KeyboardInterrupt):
            with output.response() as write:
                write("尚未结束")
                raise KeyboardInterrupt()
        self.assertEqual(console._live_stack, [])
        console.print("下一条日志")
        self.assertIn("下一条日志", target.getvalue())


if __name__ == "__main__":
    unittest.main()
