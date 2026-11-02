"""Agent 主循环：请求模型、检查权限、执行工具并回填结果。"""

import json
from contextlib import nullcontext
from dataclasses import dataclass
from time import perf_counter
from mini_agent.tools import TOOL_SCHEMAS
from mini_agent.tool_registry import TOOL_HANDLERS
from mini_agent.hooks import trigger_hooks
from mini_agent.context_compact import ContextCompactor


@dataclass
class _RunTiming:
    """仅属于本次循环的统计；父、子 Agent 分别创建，避免相互覆盖。"""

    name: str
    model_calls: int = 0
    tool_calls: int = 0
    model_seconds: float = 0.0
    tool_seconds: float = 0.0
    check_seconds: float = 0.0
    exit_reason: str = "异常"
    active_tool_call_id: str | None = None


def _complete_pending_tool_results(messages, active_call_id, reason):
    """失败时补齐当前工具批次，保留已经返回的结果，不重试操作。"""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "assistant":
            continue

        calls = message.get("tool_calls") or []
        returned_ids = {
            item.get("tool_call_id")
            for item in messages[index + 1:]
            if item.get("role") == "tool"
        }
        repaired = 0
        for call in calls:
            call_id = call["id"]
            if call_id in returned_ids:
                continue
            if call_id == active_call_id:
                result = (
                    f"本次工具处理因{reason}停止，执行结果未确认。"
                    "操作可能已产生影响，重试前先检查实际状态。"
                )
            else:
                result = f"本次工具未执行：同一批次已因{reason}停止。"
            messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
            repaired += 1
        if repaired:
            print(f"[消息修复] 已补齐 {repaired} 条工具结果，未重新执行任何工具。")
        # 只检查最后一条模型消息，不改写已经完成的旧批次。
        return


def agent_loop(
    llm,
    messages,
    tool_schemas=None,
    tool_handlers=None,
    max_turns=None,
    agent_name="主 Agent",
    output=None,
):
    """统计从循环开始到返回的总耗时，包含子任务和用户审批等待。"""
    timing = _RunTiming(name=agent_name)
    started = perf_counter()

    try:
        return _agent_loop(
            llm, messages, tool_schemas, tool_handlers, max_turns, timing, output,
        )
    except KeyboardInterrupt:
        timing.exit_reason = "用户中断"
        _complete_pending_tool_results(messages, timing.active_tool_call_id, "用户中断")
        raise
    except Exception as error:
        _complete_pending_tool_results(
            messages, timing.active_tool_call_id, f"异常（{type(error).__name__}）",
        )
        raise
    finally:
        # 即使请求失败、被中断或达到轮次上限，也输出本次耗时。
        elapsed = perf_counter() - started
        other = max(
            0.0,
            elapsed - timing.model_seconds - timing.tool_seconds - timing.check_seconds,
        )
        print(
            f"[结束日志] {timing.name} | 本次总耗时：{elapsed:.2f} 秒 | "
            f"模型请求：{timing.model_calls} 次 / {timing.model_seconds:.2f} 秒 | "
            f"工具请求：{timing.tool_calls} 次 | 工具执行：{timing.tool_seconds:.2f} 秒 | "
            f"执行前检查：{timing.check_seconds:.2f} 秒 | 其他：{other:.2f} 秒 | "
            f"退出原因：{timing.exit_reason}",
            flush=True,
        )


def _agent_loop(llm, messages, tool_schemas, tool_handlers, max_turns, timing, output):
    """llm 是模型客户端，messages 是持续追加内容的对话列表。"""
    # 首次请求模型前准备配置；None 表示使用默认配置，空集合则原样保留。
    if tool_schemas is None:
        tool_schemas = TOOL_SCHEMAS

    if tool_handlers is None:
        tool_handlers = TOOL_HANDLERS

    # 当前循环允许使用的工具名称；执行时也会检查这个范围。
    allowed_names = {
        schema["function"]["name"]
        for schema in tool_schemas
    }

    # 连续未调用计划工具的工具轮次数；每次启动循环时重新计数。
    rounds_since_todo = 0
    turns = 0

    # 本次 Agent 运行复用一个管理器，不必每轮重新创建。
    compactor = ContextCompactor()

    while True:
        # 每次请求模型算一轮，包括 Stop 回调要求继续的情况。
        if max_turns is not None and turns >= max_turns:
            timing.exit_reason = "轮次上限"
            notice = f"任务因达到 {max_turns} 轮上限而停止，尚未获得最终回答。"
            messages.append({"role": "user", "content": f"<运行状态>{notice}</运行状态>"})
            return notice

        # 每次请求模型前，先整理整体上下文。
        messages[:] = compactor.prepare(messages)
        turns += 1

        # response 是完整响应，message 是第一份候选回答中的消息。
        timing.model_calls += 1
        streaming = getattr(llm, "stream_enabled", False) is True
        waiting = "接收流式响应……" if streaming else "等待完整响应……"
        print(
            f"[模型请求] {timing.name} 第 {turns} 轮，"
            f"消息 {len(messages)} 条，{waiting}",
            flush=True,
        )
        request_started = perf_counter()
        response = None
        try:
            # 展示上下文先关闭，再打印耗时或进入工具权限确认。
            display = output.response() if output is not None else nullcontext(None)
            with display as on_text:
                if streaming and on_text is not None:
                    response = llm.chat(messages, tool_schemas, on_text=on_text)
                else:
                    response = llm.chat(messages, tool_schemas)
        finally:
            request_seconds = perf_counter() - request_started
            timing.model_seconds += request_seconds
            # 服务返回用量时附上 token 数，帮助观察上下文及输出是否过长。
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "completion_tokens", None)
            token_info = ""
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                token_info = f"，输入/输出 token：{input_tokens}/{output_tokens}"
            print(
                f"[模型耗时] {timing.name} 第 {turns} 轮："
                f"{request_seconds:.2f} 秒{token_info}",
                flush=True,
            )
        message = response.choices[0].message

        # 转成字典保存模型消息，包含它提出的工具调用；省略值为 None 的字段。
        messages.append(message.model_dump(exclude_none=True))

        # 没有工具调用时，先让结束回调决定是否允许退出。
        if not message.tool_calls:
            continuation = trigger_hooks("Stop", messages)

            if continuation is not None:
                # 将回调提出的后续要求写入上下文，让模型继续处理。
                messages.append(
                    {
                        "role": "user",
                        "content": continuation,
                    }
                )
                continue

            timing.exit_reason = "完成"
            return message.content

        # 一份模型响应算一轮，不能按其中的工具个数累计提醒次数。
        used_todo = False
        timing.tool_calls += len(message.tool_calls)
        # tool_call：本轮的某次工具调用；一轮可能请求多个工具。
        for tool_call in message.tool_calls:
            timing.active_tool_call_id = tool_call.id
            tool_name = tool_call.function.name
            # arguments：将模型提供的 JSON 参数字符串解析为 Python 字典。
            arguments = json.loads(tool_call.function.arguments)

            # 不仅限制模型看到什么，也检查它实际请求的工具。
            if tool_name not in allowed_names:
                raise ValueError(f"当前 Agent 不允许使用工具：{tool_name}")

            handler = tool_handlers.get(tool_name)

            if handler is None:
                raise ValueError(f"未知工具：{tool_name}")

            # blocked：执行前回调返回的拦截信息；None 表示可以继续。
            check_started = perf_counter()
            try:
                blocked = trigger_hooks("PreToolUse", tool_name, arguments)
            finally:
                timing.check_seconds += perf_counter() - check_started

            if blocked is None:
                tool_started = perf_counter()
                try:
                    result = handler(**arguments)
                finally:
                    # task 的耗时包含整个子 Agent；不要再把子日志的时间加到这里。
                    tool_seconds = perf_counter() - tool_started
                    timing.tool_seconds += tool_seconds
                    print(
                        f"[工具耗时] {timing.name} 工具：{tool_name}，"
                        f"耗时：{tool_seconds:.2f} 秒",
                        flush=True,
                    )
                status = "已执行"
                # 与教材一致：统计计划工具是否被调用，不表示清单校验一定成功。
                if tool_name == "todo_write":
                    used_todo = True
            else:
                result = str(blocked)
                status = "已拒绝"

            # 先保存真实结果，后置 Hook 或输出日志出错也不会丢失执行记录。
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                }
            )
            timing.active_tool_call_id = None
            # 只有工具实际返回后，才触发执行后回调。
            if blocked is None:
                trigger_hooks("PostToolUse", tool_name, arguments, result)

            # 允许和拒绝都记录处理结果；已执行不代表工具一定执行成功。
            print(f"[工具处理结果] 工具：{tool_name}，状态：{status}")
            if blocked is not None:
                print(f"[拒绝原因] {result}")
            # 回填完本轮全部结果后，while 会再次请求模型。

        # 本轮工具结果已经全部回填，计划提醒还没有加入。
        before_chars = compactor.estimate_chars(messages)
        compactor.tool_result_budget(messages)
        after_chars = compactor.estimate_chars(messages)

        if after_chars < before_chars:
            print(
                "[工具结果归档] "
                f"历史估算大小：{before_chars} → {after_chars} 字符"
            )

        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if "todo_write" in allowed_names and rounds_since_todo >= 3:
            # 本项目使用 OpenAI 消息格式：先回填本轮所有工具结果，再加入提醒。
            # 不伪造 role=tool 的消息，避免出现没有对应调用 ID 的工具结果。
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "<reminder>已连续三轮未调用 todo_write。"
                        "若当前是多步骤任务，请检查并更新完整任务清单；"
                        "简单任务无需为了清单增加步骤。</reminder>"
                    ),
                }
            )
            print("[计划提醒] 已将检查任务清单的提醒加入上下文。")
            rounds_since_todo = 0
