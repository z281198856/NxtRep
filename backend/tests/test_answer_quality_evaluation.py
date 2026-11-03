import pytest

from nxtrep_backend.evaluation.answer_quality import check_volume_answer


@pytest.mark.parametrize(
    "message",
    [
        "容量按重量乘次数计算。已记录的热身组也计入容量，不会因为标记为热身就被剔除；作废的组不计入。",
        "容量按重量乘次数计算。热身组会算进总量。正式组完成率不包含热身组。",
        "总容量是重量乘次数。正式组完成率不包含热身组，容量则包括已记录的热身组。",
        "容量是负重与次数的累计。已记录的热身组属于总负荷的一部分。",
    ],
)
def test_correct_metric_contract_does_not_cross_negation_between_clauses(message):
    assert all(check_volume_answer(message).values())


@pytest.mark.parametrize(
    "message",
    [
        "容量按重量乘次数计算。热身组不计入容量。",
        "容量按重量乘次数计算。总量不包含热身组。",
        "容量按重量乘次数计算。热身组也计入容量，但是热身组不计入总量。",
        "容量按重量乘次数计算。不应把热身组计入容量。",
        "容量按重量乘次数计算。正式组完成率不包含热身组。",
    ],
)
def test_incorrect_or_missing_warmup_definition_still_fails(message):
    assert check_volume_answer(message)["warmups_explained"] is False


def test_observed_colon_separates_capacity_from_completion_rate_subject():
    message = (
        "本应用的训练容量按每组重量乘次数累加，**已记录的热身组也计入**。"
        "容量和正式组完成率是两个独立指标：完成率只统计正式组，不包含热身组，"
        "所以容量数字偏大不代表正式组更多。"
    )
    assert all(check_volume_answer(message).values())
    wrong = "容量按重量乘次数累加，热身组计入容量。但容量不包含热身组，正式组完成率另算。"
    assert check_volume_answer(wrong)["warmups_explained"] is False
