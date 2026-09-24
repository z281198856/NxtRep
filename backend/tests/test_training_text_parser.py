from uuid import UUID

import pytest

from nxtrep_backend.services.training_text import TrainingTextParseError, parse_training_text

PRESS = UUID("10000000-0000-4000-8000-000000000031")
ROW = UUID("10000000-0000-4000-8000-000000000032")
EXERCISES = [
    (PRESS, "哑铃地板卧推", "地板卧推"),
    (ROW, "单臂哑铃划船", "哑铃划船"),
]


def test_parses_weekday_headings_ranges_and_aliases():
    days = parse_training_text(
        "周一：哑铃地板卧推 3×8-12，哑铃划船 3组×10次\n周四：\n- 哑铃地板卧推 4×6",
        EXERCISES,
    )
    assert [day["day_index"] for day in days] == [1, 4]
    assert [day["name"] for day in days] == ["周一训练", "周四训练"]
    assert days[0]["exercises"][0]["exercise_id"] == str(PRESS)
    assert days[0]["exercises"][0]["rep_max"] == 12
    assert days[0]["exercises"][1]["exercise_name"] == "单臂哑铃划船"
    assert days[1]["exercises"][0]["target_sets"] == 4


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("周一：完全不存在 3×8", "动作库中找不到"),
        ("周一：哑铃地板卧推三组八次", "无法识别"),
        ("周一：哑铃地板卧推 0×8", "组数须为"),
        ("周一：哑铃地板卧推 3×12-8", "组数须为"),
        ("周一：哑铃地板卧推 3×8\n周一：哑铃划船 3×8", "出现了两次"),
    ],
)
def test_rejects_unreadable_or_unsafe_entries(text, expected):
    with pytest.raises(TrainingTextParseError, match=expected):
        parse_training_text(text, EXERCISES)


def test_rejects_ambiguous_alias_instead_of_picking_first():
    with pytest.raises(TrainingTextParseError, match="对应多个动作"):
        parse_training_text(
            "第1天：卧推 3×8",
            [
                (PRESS, "杠铃卧推", "卧推"),
                (ROW, "哑铃卧推", "卧推"),
            ],
        )
