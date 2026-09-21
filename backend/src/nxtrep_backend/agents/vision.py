import base64
from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from nxtrep_backend.services.agent_media import ResolvedAgentImage


def build_glm_vision_content(
    *,
    question: str,
    images: Sequence[ResolvedAgentImage],
) -> list[dict[str, object]]:
    normalized_question = question.strip()

    if not normalized_question:
        raise ValueError("question must not be blank")

    if not images:
        raise ValueError("At least one image is required")

    purposes = ", ".join(image.purpose.value for image in images)

    prompt = (
        f"用户问题：{normalized_question}\n"
        f"图片用途依次为：{purposes}\n"
        "请只根据图片中可以观察到的信息回答。"
        "无法确定的信息必须说明不确定性；"
        "不要根据身体照片作医学诊断。"
    )

    content: list[dict[str, object]] = [
        {
            "type": "text",
            "text": prompt,
        }
    ]

    for image in images:
        encoded = base64.b64encode(image.data).decode("ascii")

        content.append(
            {
                "type": "image_url",
                "image_url": {"url": (f"data:{image.content_type};base64,{encoded}")},
            }
        )

    return content


class VisionModelResponseError(RuntimeError):
    pass


class GlmVisionAnalyzer:
    def __init__(
        self,
        model: BaseChatModel,
    ) -> None:
        self._model = model

    async def analyze(
        self,
        *,
        question: str,
        images: Sequence[ResolvedAgentImage],
    ) -> str:
        content = build_glm_vision_content(
            question=question,
            images=images,
        )

        response = await self._model.ainvoke(
            [
                HumanMessage(content=content),
            ]
        )

        text = self._extract_text(response.content)

        if not text:
            raise VisionModelResponseError("Vision model returned no text")

        return text

    @staticmethod
    def _extract_text(content: object) -> str:
        if isinstance(content, str):
            return content.strip()

        if not isinstance(content, list):
            return ""

        parts: list[str] = []

        for block in content:
            if isinstance(block, str):
                text = block.strip()
            elif isinstance(block, dict):
                value = block.get("text")
                text = value.strip() if isinstance(value, str) else ""
            else:
                text = ""

            if text:
                parts.append(text)

        return "\n".join(parts)
