"""上下文管理：估算历史大小，后续逐步加入归档和压缩。"""

import json
from pathlib import Path
from uuid import uuid4



class ContextCompactor:
    # 教学用整理阈值，不是模型真实的上下文窗口。
    CONTEXT_CHAR_LIMIT = 50_000
    # 本轮工具结果超过这个预算，开始归档其中的大结果。
    TOOL_RESULT_BATCH_CHAR_LIMIT = 200_000
    # 小结果暂时保留，避免为了很短的内容创建归档文件。
    LARGE_RESULT_CHAR_LIMIT = 30_000
    # 保留最近三条已读工具结果的现有正文。
    KEEP_RECENT_RESULTS = 3
    # 历史摘要后，至少保留最近十条完整消息。
    KEEP_RECENT_MESSAGES = 10

    def __init__(self):
        # 归档目录放在项目中，后续可以通过 read_file 读取。
        project_dir = Path(__file__).resolve().parent.parent
        self.tool_results_dir = (
            project_dir / ".task_outputs" / "tool-results"
        )
        self.transcript_dir = project_dir / ".transcripts"

    @staticmethod
    def estimate_chars(messages: list[dict]) -> int:
        """把消息转成 JSON 文本，估算当前历史的字符数。"""
        text = json.dumps(messages, ensure_ascii=False)
        return len(text)


    def needs_compaction(self, messages: list[dict]) -> bool:
        """超过阈值时返回 True；这里只判断，暂不修改历史。"""
        return self.estimate_chars(messages) > self.CONTEXT_CHAR_LIMIT


    def save_output(self, output: str) -> Path:
        """保存完整工具结果，成功后返回文件路径。"""
        self.tool_results_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # 文件名由程序生成，避免重名或使用模型提供的路径。
        path = self.tool_results_dir / f"{uuid4().hex}.txt"
        path.write_text(output, encoding="utf-8")

        return path

    def persisted_preview(
            self,
            output: str,
            preview_chars: int = 2_000,
    ) -> str:
        """保存全文或复用已有归档，返回路径和内容预览。"""
        if preview_chars <= 0:
            raise ValueError("预览字符数必须大于 0。")

        path = self.persisted_output_path(output)
        size_note = ""

        if path is None:
            path = self.save_output(output)
            preview = output[:preview_chars]
            size_note = f"原始内容：{len(output)} 个字符\n"
        else:
            # 已归档时，从原文件读取预览，不重复保存归档说明。
            with path.open(encoding="utf-8") as saved:
                preview = saved.read(preview_chars)

        return (
            "<已归档工具结果>\n"
            f"完整内容位置：{path.as_posix()}\n"
            f"{size_note}"
            "以下仅为开头预览，需要其他部分时请读取归档文件：\n"
            f"{preview}\n"
            "</已归档工具结果>"
        )


    def tool_result_budget(
        self,
        messages: list[dict],
    ) -> list[dict]:
        """本轮工具结果超出预算时，优先归档较大的结果。"""
        results = []

        # 从末尾查找本轮连续的工具结果。
        for message in reversed(messages):
            if message.get("role") != "tool":
                break
            results.append(message)

        total_chars = sum(
            len(message["content"])
            for message in results
        )

        # sorted 生成新列表，不改变原来消息的先后顺序。
        largest_first = sorted(
            results,
            key=lambda message: len(message["content"]),
            reverse=True,
        )

        for message in largest_first:
            if total_chars <= self.TOOL_RESULT_BATCH_CHAR_LIMIT:
                break

            output = message["content"]

            if len(output) <= self.LARGE_RESULT_CHAR_LIMIT:
                continue

            # 先成功保存全文，才能替换上下文中的原内容。
            replacement = self.persisted_preview(output)

            # 只有确实变短才替换。
            if len(replacement) >= len(output):
                continue

            message["content"] = replacement
            total_chars -= len(output) - len(replacement)

        return messages


    @staticmethod
    def consumed_tool_results(
        messages: list[dict],
    ) -> list[dict]:
        """找出已经进入过后续模型请求的工具结果。"""
        # 从后往前，找到最近一次模型响应的位置。
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") != "assistant":
                continue

            # 只收集这次响应之前的工具结果。
            return [
                message
                for message in messages[:index]
                if message.get("role") == "tool"
            ]

        # 没有模型响应，暂时不将任何工具结果视为已读。
        return []


    def persisted_output_path(self, output: str) -> Path | None:
        """识别本程序生成的归档说明，找到已有的全文文件。"""
        candidate = None

        if output.startswith("<已归档工具结果>\n"):
            for line in output.splitlines():
                if line.startswith("完整内容位置："):
                    candidate = line.removeprefix("完整内容位置：")
                    break

        prefix = "[旧工具结果已归档："
        if output.startswith(prefix) and output.endswith("]"):
            candidate = output[len(prefix):-1]

        if not candidate:
            return None

        path = Path(candidate).resolve()

        # 路径必须属于归档目录，且文件仍然存在。
        if not path.is_relative_to(self.tool_results_dir.resolve()):
            return None
        if not path.is_file():
            return None

        return path


    def micro_compact(
        self,
        messages: list[dict],
        target_chars: int | None = None,
    ) -> list[dict]:
        """优先缩短较旧的已读工具结果，不删除调用记录。"""
        if target_chars is None:
            target_chars = int(self.CONTEXT_CHAR_LIMIT * 0.8)

        consumed = self.consumed_tool_results(messages)

        # 按原来的时间顺序，排除最近三条已读结果。
        candidates = consumed[:-self.KEEP_RECENT_RESULTS]

        for message in candidates:
            if self.estimate_chars(messages) <= target_chars:
                break

            output = message["content"]

            # 很短的结果不值得单独归档。
            if len(output) <= 120:
                continue

            # 已有归档则复用；没有归档才保存全文。
            path = self.persisted_output_path(output)
            if path is None:
                path = self.save_output(output)

            replacement = (
                f"[旧工具结果已归档：{path.as_posix()}]"
            )

            if len(replacement) >= len(output):
                continue

            message["content"] = replacement

        return messages


    def prepare(self, messages: list[dict]) -> list[dict]:
        """请求模型前检查整体历史，超限时先进行微压缩。"""
        if not self.needs_compaction(messages):
            return messages

        before_chars = self.estimate_chars(messages)
        target_chars = int(self.CONTEXT_CHAR_LIMIT * 0.8)

        self.micro_compact(messages, target_chars)

        if self.needs_compaction(messages):
            self.fit_tool_results(messages, target_chars)

        after_chars = self.estimate_chars(messages)

        print(
            "[上下文整理] "
            f"历史估算大小：{before_chars} → {after_chars} 字符"
        )

        if after_chars > self.CONTEXT_CHAR_LIMIT:
            print(
                "[上下文提醒] 工具结果整理后仍超过整理阈值，"
                "后续还需要其他压缩策略。"
            )

        return messages


    def fit_tool_results(
        self,
        messages: list[dict],
        target_chars: int,
    ) -> list[dict]:
        """整体仍超限时，将较大的工具结果缩成路径和预览。"""
        results = [
            message
            for message in messages
            if message.get("role") == "tool"
        ]

        largest_first = sorted(
            results,
            key=lambda message: len(message["content"]),
            reverse=True,
        )

        for message in largest_first:
            if self.estimate_chars(messages) <= target_chars:
                break

            output = message["content"]

            # 已经很短的内容不再处理。
            if len(output) <= 1_000:
                continue

            replacement = self.persisted_preview(
                output,
                preview_chars=1_000,
            )

            if len(replacement) < len(output):
                message["content"] = replacement

        return messages


    def write_transcript(self, messages: list[dict]) -> Path:
        """保存当前完整消息历史，成功后返回文件路径。"""
        self.transcript_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            self.transcript_dir
            / f"transcript_{uuid4().hex}.jsonl"
        )

        # x 表示新建文件；如果文件已存在则报错，避免覆盖。
        with path.open("x", encoding="utf-8") as transcript:
            for message in messages:
                line = json.dumps(
                    message,
                    ensure_ascii=False,
                )
                transcript.write(line + "\n")

        return path