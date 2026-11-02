"""读取并校验环境变量，将配置集中保存到 Settings 对象。"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """配置数据类；frozen=True 表示创建后不能直接重新赋值属性。"""

    api_key: str  # API 访问密钥。
    base_url: str  # 模型服务的 API 地址。
    model: str  # 请求使用的模型名称。
    temperature: float  # 采样温度，影响生成结果的随机性。
    stream: bool  # 是否接收真实流式响应。
    timeout: int  # 请求超时设置，单位为秒。

    @classmethod
    def from_env(cls) -> "Settings":
        """读取环境配置并创建对象；cls 表示当前的 Settings 类。"""
        # 加载 .env 文件；默认不覆盖进程中已经存在的环境变量。
        load_dotenv()

        # raw：必填配置的原始值，此时尚未去除首尾空白。
        raw = {
            "LLM_API_KEY": os.getenv("LLM_API_KEY"),
            "LLM_BASE_URL": os.getenv("LLM_BASE_URL"),
            "LLM_MODEL": os.getenv("LLM_MODEL"),
        }
        # missing：未设置或仅包含空白的环境变量名称。
        missing = [name for name, value in raw.items() if not value or not value.strip()]
        if missing:
            raise ValueError("缺少环境变量：" + ", ".join(missing))

        # 环境变量都是字符串：先转为浮点数，再检查取值范围。
        temperature_text = os.getenv("LLM_TEMPERATURE", "0").strip()
        try:
            temperature = float(temperature_text)
        except ValueError as exc:
            # exc 是原始异常；from exc 保留异常原因，便于定位问题。
            raise ValueError("LLM_TEMPERATURE 必须是数字") from exc
        if not 0 <= temperature <= 2:
            raise ValueError("LLM_TEMPERATURE 必须在 0 到 2 之间")

        # 不用 bool("false")：非空字符串会被判为 True，需要显式比较内容。
        stream_text = os.getenv("LLM_STREAM", "true").strip().lower()
        if stream_text not in {"true", "false"}:
            raise ValueError("LLM_STREAM 必须是 true 或 false")
        stream = stream_text == "true"

        # 超时配置转换成正整数，未设置时默认 60 秒。
        timeout_text = os.getenv("LLM_TIMEOUT", "60").strip()
        try:
            timeout = int(timeout_text)
        except ValueError as exc:
            raise ValueError("LLM_TIMEOUT 必须是整数") from exc
        if timeout <= 0:
            raise ValueError("LLM_TIMEOUT 必须大于 0")

        # 使用校验后的值创建并返回 Settings 对象。
        return cls(
            api_key=raw["LLM_API_KEY"].strip(),
            base_url=raw["LLM_BASE_URL"].strip(),
            model=raw["LLM_MODEL"].strip(),
            temperature=temperature,
            stream=stream,
            timeout=timeout,
        )
