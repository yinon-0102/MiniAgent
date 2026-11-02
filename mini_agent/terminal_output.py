"""终端展示层：流式刷新 Markdown，不参与模型或工具逻辑。"""

from contextlib import contextmanager
from time import monotonic

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown


class TerminalOutput:
    def __init__(self, console=None):
        self.console = console if console is not None else Console()
        self.text = ""

    @contextmanager
    def response(self):
        """每次模型请求独立展示，退出时恢复终端与日志输出。"""
        self.text = ""
        live = None
        last_refresh = 0.0

        def write(part):
            nonlocal live, last_refresh
            first = not self.text
            self.text += part
            if first:
                self.console.print("模型输出 >", markup=False)
            if not self.console.is_terminal:
                # 管道和日志文件直接追加文本，不输出光标控制符。
                self.console.file.write(part)
                self.console.file.flush()
                return
            if live is None:
                live = Live(Markdown(self.text), console=self.console,
                            auto_refresh=False, vertical_overflow="ellipsis")
                live.start()
            now = monotonic()
            # 限制重绘频率；收到片段后累计，结束时强制展示最终结果。
            refresh = first or now - last_refresh >= 0.1
            live.update(Markdown(self.text), refresh=refresh)
            if refresh:
                last_refresh = now

        try:
            yield write
        finally:
            if live is not None:
                live.update(Markdown(self.text))
                live.stop()
            elif self.text:
                self.console.file.write("\n")
                self.console.file.flush()

    def finish(self, answer):
        """流式已显示的正文不重复打印；兼容完整响应和停止说明。"""
        answer = answer or "模型未返回文本内容。"
        if self.text and answer == self.text:
            return
        if self.console.is_terminal:
            self.console.print("模型输出 >", markup=False)
            self.console.print(Markdown(answer))
        else:
            self.console.print(f"模型输出 > {answer}", markup=False, highlight=False,
                               soft_wrap=True)
