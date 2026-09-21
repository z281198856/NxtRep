import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

_CONTENT_TYPE_TO_FORMAT = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    data: bytes
    content_type: str
    width: int
    height: int


class ImageContentValidationError(RuntimeError):
    pass


class PillowImageContentProcessor:
    def __init__(
        self,
        *,
        max_input_bytes: int,
        max_output_bytes: int,
        max_pixels: int,
        max_dimension: int,
    ) -> None:
        if (
            min(
                max_input_bytes,
                max_output_bytes,
                max_pixels,
                max_dimension,
            )
            <= 0
        ):
            raise ValueError("Image processing limits must be positive")

        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes
        self._max_pixels = max_pixels
        self._max_dimension = max_dimension

    def process(
        self,
        data: bytes,
        *,
        declared_content_type: str,
    ) -> ProcessedImage:
        content_type = declared_content_type.strip().lower()
        expected_format = _CONTENT_TYPE_TO_FORMAT.get(content_type)

        if expected_format is None:
            raise ImageContentValidationError("Only JPEG, PNG and WebP images are accepted")

        if not data or len(data) > self._max_input_bytes:
            raise ImageContentValidationError("Image input size is outside the allowed range")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter(
                    "error",
                    Image.DecompressionBombWarning,
                )

                return self._decode_and_reencode(
                    data=data,
                    content_type=content_type,
                    expected_format=expected_format,
                )
        except ImageContentValidationError:
            raise
        except (
            UnidentifiedImageError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
            OSError,
            SyntaxError,
            ValueError,
        ) as exc:
            raise ImageContentValidationError("Image content could not be safely decoded") from exc

    def _decode_and_reencode(
        self,
        *,
        data: bytes,
        content_type: str,
        expected_format: str,
    ) -> ProcessedImage:
        with Image.open(
            BytesIO(data),
            formats=tuple(_CONTENT_TYPE_TO_FORMAT.values()),
        ) as image:
            if image.format != expected_format:
                raise ImageContentValidationError(
                    "Decoded image format does not match declared content type"
                )

            if getattr(image, "is_animated", False):
                raise ImageContentValidationError("Animated images are not supported")

            width, height = image.size

            if width <= 0 or height <= 0:
                raise ImageContentValidationError("Image dimensions must be positive")

            if width * height > self._max_pixels:
                raise ImageContentValidationError("Image exceeds the configured pixel limit")

            if max(width, height) > self._max_dimension:
                raise ImageContentValidationError("Image exceeds the configured dimension limit")

            image.load()
            oriented = ImageOps.exif_transpose(image)
            sanitized = self._normalize_pixels(
                oriented,
                expected_format,
            )

            output = BytesIO()
            sanitized.save(
                output,
                format=expected_format,
                **self._save_options(expected_format),
            )

            encoded = output.getvalue()

            if not encoded or len(encoded) > self._max_output_bytes:
                raise ImageContentValidationError("Image output size is outside the allowed range")

            return ProcessedImage(
                data=encoded,
                content_type=content_type,
                width=sanitized.width,
                height=sanitized.height,
            )

    @staticmethod
    def _normalize_pixels(
        image: Image.Image,
        image_format: str,
    ) -> Image.Image:
        if image_format == "JPEG":
            return image.convert("RGB")

        has_alpha = "A" in image.getbands() or image.mode == "P" and "transparency" in image.info

        return image.convert("RGBA" if has_alpha else "RGB")

    @staticmethod
    def _save_options(image_format: str) -> dict[str, object]:
        common: dict[str, object] = {
            "exif": b"",
            "icc_profile": None,
        }

        if image_format == "JPEG":
            return {
                **common,
                "quality": 90,
                "optimize": True,
            }

        if image_format == "PNG":
            return {
                **common,
                "optimize": True,
            }

        return {
            **common,
            "quality": 90,
            "method": 4,
            "xmp": b"",
        }
