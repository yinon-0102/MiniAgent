"""任务清单：保存计划状态，并生成便于阅读的文本。"""


class TodoManager:
    def __init__(self):
        # 每个管理器对象拥有自己的任务列表。
        self.items: list[dict] = []

    def render(self) -> str:
        """将当前任务清单转换成文本，不修改任务状态。"""
        if not self.items:
            return "当前没有任务。"

        # 任务状态对应的显示符号。
        markers = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
        }

        lines = []
        completed_count = 0

        for item in self.items:
            marker = markers[item["status"]]
            lines.append(f"{marker} {item['content']}")

            if item["status"] == "completed":
                completed_count += 1

        lines.append(
            f"\n已完成：{completed_count}/{len(self.items)}"
        )

        return "\n".join(lines)


    def update(self, todos: list) -> str:
        """检查新清单；全部合法后替换旧状态，并返回展示文本。"""
        if not isinstance(todos, list):
            raise ValueError("任务清单必须是列表。")

        if len(todos) > 20:
            raise ValueError("任务数量不能超过 20 项。")

        # 临时保存校验通过的任务，暂时不修改旧清单。
        validated = []
        in_progress_count = 0

        for index, todo in enumerate(todos, start=1):
            if not isinstance(todo, dict):
                raise ValueError(f"第 {index} 项任务必须是字典。")

            content = todo.get("content")
            status = todo.get("status", "pending")

            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"第 {index} 项任务内容必须是非空字符串。")

            if not isinstance(status, str):
                raise ValueError(f"第 {index} 项任务状态必须是字符串。")

            content = content.strip()
            status = status.strip().lower()

            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"第 {index} 项任务状态无效：{status}")

            if status == "in_progress":
                in_progress_count += 1

            validated.append(
                {
                    "content": content,
                    "status": status,
                }
            )

        if in_progress_count > 1:
            raise ValueError("同一时间最多只能有一项任务正在处理。")

        # 所有检查通过后，才整体替换旧清单。
        self.items = validated
        return self.render()