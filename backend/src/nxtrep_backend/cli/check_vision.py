import asyncio
from io import BytesIO
from uuid import uuid4

from PIL import Image

from nxtrep_backend.agents.vision import GlmVisionAnalyzer
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.providers.models import ModelConfigurationError, build_vision_model
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import ResolvedAgentImage


def _build_test_image() -> bytes:
    output = BytesIO()

    with Image.new(
        "RGB",
        (64, 64),
        color=(220, 40, 40),
    ) as image:
        image.save(
            output,
            format="JPEG",
            quality=85,
        )

    return output.getvalue()


async def check_vision_connectivity() -> int:
    try:
        model = build_vision_model(get_settings())
    except ModelConfigurationError as exc:
        print(f"GLM vision configuration check failed: {exc}")
        return 1

    analyzer = GlmVisionAnalyzer(model)
    image = ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.CHAT_ATTACHMENT,
        content_type="image/jpeg",
        data=_build_test_image(),
    )

    try:
        observation = await analyzer.analyze(
            question="只用一句话描述这张测试图片的主要颜色。",
            images=[image],
        )
    except Exception as exc:
        print(f"GLM vision connectivity check failed: {type(exc).__name__}: {exc}")
        return 1

    print("GLM vision connectivity check passed.")
    safe_observation = observation[:500].encode("unicode_escape").decode("ascii")
    print(f"Model response: {safe_observation}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(check_vision_connectivity()))


if __name__ == "__main__":
    main()
