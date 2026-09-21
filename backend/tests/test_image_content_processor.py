from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from nxtrep_backend.providers.image_processing import (
    ImageContentValidationError,
    PillowImageContentProcessor,
)


def encode_image(
    *,
    image_format: str,
    size: tuple[int, int] = (40, 20),
    exif: Image.Exif | None = None,
    pnginfo: PngImagePlugin.PngInfo | None = None,
) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", size, color=(80, 120, 160))
    options: dict[str, object] = {}
    if exif is not None:
        options["exif"] = exif
    if pnginfo is not None:
        options["pnginfo"] = pnginfo
    image.save(output, format=image_format, **options)
    return output.getvalue()


def test_jpeg_is_oriented_reencoded_and_stripped_of_exif() -> None:
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private description"
    source = encode_image(image_format="JPEG", exif=exif)
    processor = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_pixels=1_000_000,
        max_dimension=4096,
    )

    result = processor.process(source, declared_content_type="image/jpeg")

    assert result.content_type == "image/jpeg"
    assert result.width == 20
    assert result.height == 40
    assert result.data != source
    with Image.open(BytesIO(result.data)) as sanitized:
        sanitized.load()
        assert sanitized.format == "JPEG"
        assert sanitized.size == (20, 40)
        assert len(sanitized.getexif()) == 0


def test_png_text_metadata_is_not_copied_to_output() -> None:
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("private-note", "should not survive")
    source = encode_image(image_format="PNG", pnginfo=pnginfo)
    processor = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_pixels=1_000_000,
        max_dimension=4096,
    )

    result = processor.process(source, declared_content_type="image/png")

    with Image.open(BytesIO(result.data)) as sanitized:
        sanitized.load()
        assert sanitized.format == "PNG"
        assert "private-note" not in sanitized.info
        assert len(sanitized.getexif()) == 0


def test_declared_content_type_must_match_decoded_format() -> None:
    source = encode_image(image_format="PNG")
    processor = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_pixels=1_000_000,
        max_dimension=4096,
    )

    with pytest.raises(ImageContentValidationError, match="does not match"):
        processor.process(source, declared_content_type="image/jpeg")


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"", "image/jpeg"),
        (b"this is not an image", "image/jpeg"),
        (encode_image(image_format="JPEG"), "image/gif"),
    ],
)
def test_empty_invalid_and_unsupported_inputs_are_rejected(
    data: bytes,
    content_type: str,
) -> None:
    processor = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_pixels=1_000_000,
        max_dimension=4096,
    )

    with pytest.raises(ImageContentValidationError):
        processor.process(data, declared_content_type=content_type)


def test_input_byte_limit_is_checked_before_decoding() -> None:
    processor = PillowImageContentProcessor(
        max_input_bytes=8,
        max_output_bytes=1024,
        max_pixels=1_000_000,
        max_dimension=4096,
    )

    with pytest.raises(ImageContentValidationError, match="input size"):
        processor.process(b"123456789", declared_content_type="image/jpeg")


def test_pixel_and_dimension_limits_are_checked_before_full_decode() -> None:
    source = encode_image(image_format="PNG", size=(101, 100))

    pixel_limited = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_pixels=10_000,
        max_dimension=4096,
    )
    with pytest.raises(ImageContentValidationError, match="pixel limit"):
        pixel_limited.process(source, declared_content_type="image/png")

    dimension_limited = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_pixels=20_000,
        max_dimension=100,
    )
    with pytest.raises(ImageContentValidationError, match="dimension limit"):
        dimension_limited.process(source, declared_content_type="image/png")


def test_animated_webp_is_rejected() -> None:
    output = BytesIO()
    first = Image.new("RGB", (20, 20), color="red")
    second = Image.new("RGB", (20, 20), color="blue")
    first.save(
        output,
        format="WEBP",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    processor = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=1024 * 1024,
        max_pixels=1_000_000,
        max_dimension=4096,
    )

    with pytest.raises(ImageContentValidationError, match="Animated"):
        processor.process(output.getvalue(), declared_content_type="image/webp")


def test_reencoded_output_must_remain_within_configured_limit() -> None:
    source = encode_image(image_format="PNG", size=(100, 100))
    processor = PillowImageContentProcessor(
        max_input_bytes=1024 * 1024,
        max_output_bytes=32,
        max_pixels=1_000_000,
        max_dimension=4096,
    )

    with pytest.raises(ImageContentValidationError, match="output size"):
        processor.process(source, declared_content_type="image/png")
