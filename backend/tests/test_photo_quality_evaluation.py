from pathlib import Path

import pytest
from pydantic import ValidationError

from nxtrep_backend.evaluation.photo_quality import (
    PhotoQualitySample,
    load_photo_samples,
    score_photo,
)


def sample(**changes):
    return PhotoQualitySample.model_validate(
        {
            "sample_id": "rice-known",
            "image_path": "meal.png",
            "expected_foods": [{"aliases": ["米饭", "熟米饭"], "amount_g": 150, "kcal": 195}],
            **changes,
        }
    )


def response(*, grams=150, kcal=195, name="熟米饭"):
    detected = {"name": name, "estimated_amount_g": grams, "amount_min_g": 100, "amount_max_g": 200}
    return {
        "recognition": {"foods": [detected]},
        "calculation": {
            "is_complete": True,
            "items": [
                {"match": {"detected": detected}, "nutrition": {"estimated": {"kcal": kcal}}}
            ],
        },
    }


def test_known_grams_and_calories_are_scored_separately():
    report = score_photo(sample(), response(grams=240, kcal=195))
    assert report["passed"] is False
    assert report["checks"]["food_recall"] is True
    assert report["checks"]["portion:米饭"] is False
    assert report["checks"]["kcal:米饭"] is True
    assert report["portion_mean_relative_error"] == pytest.approx(0.6)
    assert report["portion_interval_coverage"] == 1


def test_names_without_weights_do_not_claim_portion_accuracy():
    report = score_photo(sample(expected_foods=[{"aliases": ["米饭"]}]), response())
    assert report["passed"] is True
    assert report["portion_mean_relative_error"] is None
    assert report["kcal_mean_relative_error"] is None
    assert report["accuracy_truth"] == "names_only"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", -10, None])
def test_invalid_model_numbers_never_pass_accuracy(bad):
    report = score_photo(sample(), response(grams=bad, kcal=bad))
    assert report["passed"] is False
    assert report["portion_mean_relative_error"] is None


def test_duplicate_food_detections_do_not_inflate_recall():
    payload = response()
    payload["recognition"]["foods"] *= 2
    report = score_photo(sample(), payload)
    assert report["food_precision"] == 0.5
    assert report["passed"] is False


def test_non_food_success_requires_empty_and_incomplete_estimate():
    truth = sample(non_food=True, expected_foods=[])
    assert (
        score_photo(
            truth,
            {
                "recognition": {"foods": []},
                "calculation": {
                    "items": [],
                    "is_complete": False,
                },
            },
        )["passed"]
        is True
    )
    assert score_photo(truth, response())["passed"] is False


def test_manifest_rejects_fake_truth_duplicate_ids_and_missing_files(tmp_path: Path):
    with pytest.raises(ValidationError):
        sample(non_food=True)
    with pytest.raises(ValidationError):
        sample(expected_foods=[{"aliases": ["  "]}])
    manifest = tmp_path / "samples.json"
    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must not be empty"):
        load_photo_samples(manifest)
    manifest.write_text(
        '[{"sample_id":"missing", "image_path":"missing.png", "non_food":true}]', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="image unavailable"):
        load_photo_samples(manifest)
