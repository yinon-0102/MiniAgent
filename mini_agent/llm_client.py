"""模型调用封装：负责单次请求，是否继续调用由 Agent 循环决定。"""

from openai import OpenAI
from openai.types.chat import ChatCompletion

from mini_agent.config import Settings


class LLMClient:
    """保存模型配置和 SDK 客户端，向 Agent 提供 chat 方法。"""

    def __init__(self, settings: Settings):
        # self 是当前对象；保存 settings 后，其他方法也能读取配置。
        self.settings = settings

        # client：SDK 客户端；创建对象时还没有发送模型请求。
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=0,  # 请求失败交给用户处理，避免隐式重试。
        )

    @property
    def stream_enabled(self):
        return self.settings.stream

    def chat(self, messages, tools, on_text=None):
        """messages 是对话记录，tools 是工具说明；返回完整响应对象。"""
        response = self.client.chat.completions.create(
            model=self.settings.model,  # 本轮请求的模型名称。
            messages=messages,  # 包含用户消息、模型消息和工具结果。
            tools=tools,  # 提供工具名称和参数格式，不是传入执行函数。
            temperature=self.settings.temperature,
            stream=self.settings.stream,
            **({"stream_options": {"include_usage": True}} if self.settings.stream else {}),
        )

        if not self.settings.stream:
            return response
        return self._collect_stream(response, on_text)

    def _collect_stream(self, stream, on_text):
        """即时传出文本，完整拼接工具参数后再交给 Agent。"""
        parts, calls = [], {}
        usage = None
        finish_reason = None
        refusal = []
        try:
            for chunk in stream:
                if chunk.usage is not None:
                    usage = chunk.usage
                for choice in chunk.choices:
                    if choice.index != 0:
                        continue
                    delta = choice.delta
                    if delta.content:
                        parts.append(delta.content)
                        if on_text is not None:
                            on_text(delta.content)
                    if delta.refusal:
                        refusal.append(delta.refusal)
                    # 多个工具的参数可能交错到达，按索引分别累计。
                    for tool in delta.tool_calls or []:
                        call = calls.setdefault(tool.index, {
                            "id": "", "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                        call["id"] += tool.id or ""
                        if tool.function:
                            call["function"]["name"] += tool.function.name or ""
                            call["function"]["arguments"] += tool.function.arguments or ""
                    if choice.finish_reason is not None:
                        finish_reason = choice.finish_reason
        finally:
            # 正常结束、断流和 Ctrl+C 都释放连接。
            stream.close()

        if finish_reason not in {"stop", "tool_calls"}:
            raise RuntimeError(f"模型流未完整结束（{finish_reason or '连接提前关闭'}），本轮工具未执行。")
        if (calls and finish_reason != "tool_calls") or (finish_reason == "tool_calls" and not calls):
            raise RuntimeError("模型流的工具调用结束标记不一致，本轮工具未执行。")
        if any(not c["id"] or not c["function"]["name"] for c in calls.values()):
            raise RuntimeError("模型流缺少工具 ID 或名称，本轮工具未执行。")

        # 保持与非流式相同的返回格式，复用历史和工具执行逻辑。
        return ChatCompletion(
            id="stream", object="chat.completion", created=0, model=self.settings.model,
            choices=[{"index": 0, "finish_reason": finish_reason, "message": {
                "role": "assistant", "content": "".join(parts) or None,
                "refusal": "".join(refusal) or None,
                "tool_calls": [calls[i] for i in sorted(calls)] or None,
            }}],
            usage=usage,
        )
