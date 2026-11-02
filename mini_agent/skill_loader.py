"""技能加载：解析技能文件，后续负责扫描、生成目录和返回全文。"""

import yaml
from pathlib import Path


class SkillLoader:
    def __init__(self, skills_dir: Path):
        # 统一为绝对路径，作为技能文件的扫描范围。
        self.skills_dir = skills_dir.resolve()

        # 技能名称 → 技能信息。
        self.skills: dict[str, dict[str, str]] = {}

        self.scan()
    @staticmethod
    def parse_frontmatter(text: str) -> tuple[dict, str]:
        """将技能文件拆分为元数据字典和正文字符串。"""
        lines = text.splitlines()

        # 没有元数据头时，将全文视为正文。
        if not lines or lines[0].strip() != "---":
            return {}, text

        # 查找元数据的结束标记，跳过第一行的开始标记。
        closing_index = None

        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing_index = index
                break

        if closing_index is None:
            raise ValueError("技能元数据缺少结束标记 ---。")

        metadata_text = "\n".join(lines[1:closing_index])
        body = "\n".join(lines[closing_index + 1:]).strip()

        try:
            metadata = yaml.safe_load(metadata_text)
        except yaml.YAMLError as error:
            raise ValueError(f"技能元数据的 YAML 格式错误：{error}") from error

        if metadata is None:
            metadata = {}

        if not isinstance(metadata, dict):
            raise ValueError("技能元数据必须是键值对结构。")

        return metadata, body


    def scan(self) -> None:
        """扫描技能目录，建立名称到技能内容的索引。"""
        scanned = {}

        for manifest in sorted(self.skills_dir.glob("*/SKILL.md")):
            # 跳过非文件，以及通过链接指向技能目录外的文件。
            if not manifest.is_file():
                continue

            if not manifest.resolve().is_relative_to(self.skills_dir):
                continue

            text = manifest.read_text(encoding="utf-8")
            metadata, _ = self.parse_frontmatter(text)

            name = metadata.get("name")
            description = metadata.get("description")

            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"技能缺少有效名称：{manifest}")

            if not isinstance(description, str) or not description.strip():
                raise ValueError(f"技能缺少有效简介：{manifest}")

            name = name.strip()
            # 将多行或多余空白整理成一行，方便展示目录。
            description = " ".join(description.split())

            if name in scanned:
                raise ValueError(f"技能名称重复：{name}")

            scanned[name] = {
                "name": name,
                "description": description,
                "content": text,
            }

        # 全部扫描成功后，再替换已有索引。
        self.skills = scanned


    def catalog(self) -> str:
        """只返回技能名称和简介，不包含正文。"""
        if not self.skills:
            return "当前没有可用技能。"

        lines = []

        for skill in self.skills.values():
            lines.append(
                f"- {skill['name']}: {skill['description']}"
            )

        return "\n".join(lines)


    def load(self, name: str) -> str:
        """按注册名称返回技能全文；参数错误时返回说明。"""
        if not isinstance(name, str) or not name.strip():
            return "技能加载失败：技能名称必须是非空字符串。"

        name = name.strip()
        skill = self.skills.get(name)

        if skill is None:
            available = "、".join(sorted(self.skills)) or "无"
            return (
                f"技能加载失败：不存在名为 {name} 的技能。"
                f"可用技能：{available}"
            )

        return skill["content"]


LOAD_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "根据技能名称读取完整的 SKILL.md。"
            "当任务符合技能目录中的适用场景时，"
            "先加载相应技能，再依据说明开展工作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "description": "技能目录中列出的名称，不是文件路径。",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}