import pytest
from pydantic import ValidationError

from nxtrep_backend.core.config import Settings, StorageConfigurationError


def _complete_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "storage_provider": "aliyun_oss",
        "oss_region": "cn-hongkong",
        "oss_endpoint": "https://oss-cn-hongkong.aliyuncs.com",
        "oss_use_cname": False,
        "oss_bucket": "nxtrep-images-dev-test",
        "oss_access_key_id": "test-access-key-id",
        "oss_access_key_secret": "test-access-key-secret",
        "oss_object_prefix": "/images/",
        "oss_upload_url_expire_seconds": 600,
        "oss_download_url_expire_seconds": 300,
        "image_max_bytes": 10 * 1024 * 1024,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_complete_oss_configuration_is_valid_and_normalized() -> None:
    settings = _complete_settings()
    configuration = settings.require_oss_configuration()

    assert configuration.region == "cn-hongkong"
    assert str(configuration.endpoint) == "https://oss-cn-hongkong.aliyuncs.com/"
    assert configuration.object_prefix == "images"
    assert "test-access-key-secret" not in repr(configuration)
    assert settings.image_max_pixels == 25_000_000
    assert settings.image_max_dimension == 8192


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image_max_pixels", 999_999),
        ("image_max_pixels", 100_000_001),
        ("image_max_dimension", 511),
        ("image_max_dimension", 20_001),
    ],
)
def test_unsafe_image_processing_limits_are_rejected(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        _complete_settings(**{field: value})


def test_oss_configuration_is_checked_only_when_requested() -> None:
    settings = Settings(_env_file=None, storage_provider=None)

    with pytest.raises(StorageConfigurationError, match="NXTREP_STORAGE_PROVIDER"):
        settings.require_oss_configuration()


def test_missing_oss_secret_reports_environment_variable_name() -> None:
    settings = _complete_settings(oss_access_key_secret=None)

    with pytest.raises(StorageConfigurationError, match="NXTREP_OSS_ACCESS_KEY_SECRET"):
        settings.require_oss_configuration()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("oss_endpoint", "http://oss-cn-hongkong.aliyuncs.com", "must use HTTPS"),
        ("oss_bucket", "Invalid_Bucket", "OSS bucket must be"),
        ("oss_object_prefix", "../images", "safe, non-empty"),
    ],
)
def test_unsafe_oss_values_are_rejected(field: str, value: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _complete_settings(**{field: value})
