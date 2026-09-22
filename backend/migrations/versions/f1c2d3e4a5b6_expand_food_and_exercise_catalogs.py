"""expand food and exercise catalogs

Revision ID: f1c2d3e4a5b6
Revises: e4b7c2a9d851
Create Date: 2026-09-22
"""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1c2d3e4a5b6"
down_revision: str | Sequence[str] | None = "e4b7c2a9d851"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = UUID("aafcebd3-aa88-47e3-9390-9ebdf3a7fe9f")


def _id(kind: str, slug: str) -> UUID:
    return uuid5(_NAMESPACE, f"nxtrep:{kind}:{slug}")


# Values are representative per-100 g references for common unbranded foods.
# The app continues to show basis amount and confidence so users can adjust the
# actual serving and replace a generic item with a label-specific custom food.
FOODS = (
    ("boiled-egg", "水煮鸡蛋", "cooked", "155", "13.0", "1.1", "11.0", ("鸡蛋", "白煮蛋")),
    ("egg-white", "熟鸡蛋白", "cooked", "52", "10.9", "0.7", "0.2", ("蛋白", "鸡蛋清")),
    ("salmon", "熟三文鱼", "cooked", "206", "22.0", "0", "12.0", ("三文鱼", "鲑鱼")),
    ("lean-beef", "熟瘦牛肉", "cooked", "250", "26.0", "0", "15.0", ("牛肉", "瘦牛肉")),
    ("shrimp", "熟虾仁", "cooked", "99", "24.0", "0.2", "0.3", ("虾仁", "虾")),
    ("tofu", "北豆腐", "ready", "116", "12.2", "3.0", "6.8", ("豆腐", "老豆腐")),
    (
        "greek-yogurt",
        "无糖希腊酸奶",
        "ready",
        "59",
        "10.3",
        "3.6",
        "0.4",
        ("希腊酸奶", "高蛋白酸奶"),
    ),
    ("whole-milk", "全脂牛奶", "ready", "61", "3.2", "4.8", "3.3", ("牛奶", "纯牛奶")),
    ("soy-milk", "无糖豆浆", "ready", "33", "2.9", "1.7", "1.6", ("豆浆", "无糖豆奶")),
    ("oats", "原味燕麦片", "dry", "379", "13.2", "67.7", "6.5", ("燕麦", "麦片")),
    ("sweet-potato", "熟红薯", "cooked", "90", "2.0", "20.7", "0.2", ("红薯", "地瓜")),
    ("whole-wheat-bread", "全麦面包", "ready", "247", "13.0", "41.0", "4.2", ("全麦吐司", "面包")),
    ("noodles", "熟面条", "cooked", "138", "4.5", "25.0", "2.1", ("面条", "白面条")),
    ("quinoa", "熟藜麦", "cooked", "120", "4.4", "21.3", "1.9", ("藜麦",)),
    ("corn", "熟甜玉米", "cooked", "96", "3.4", "21.0", "1.5", ("玉米", "甜玉米")),
    ("potato", "熟土豆", "cooked", "93", "2.5", "21.2", "0.1", ("土豆", "马铃薯")),
    ("banana", "香蕉", "raw", "89", "1.1", "22.8", "0.3", ("香蕉肉",)),
    ("apple", "苹果", "raw", "52", "0.3", "13.8", "0.2", ("鲜苹果",)),
    ("blueberry", "蓝莓", "raw", "57", "0.7", "14.5", "0.3", ("鲜蓝莓",)),
    ("orange", "橙子", "raw", "47", "0.9", "11.8", "0.1", ("鲜橙",)),
    ("spinach", "熟菠菜", "cooked", "23", "3.0", "3.8", "0.3", ("菠菜",)),
    ("tomato", "番茄", "raw", "18", "0.9", "3.9", "0.2", ("西红柿",)),
    ("cucumber", "黄瓜", "raw", "15", "0.7", "3.6", "0.1", ("青瓜",)),
    ("carrot", "熟胡萝卜", "cooked", "35", "0.8", "8.2", "0.2", ("胡萝卜",)),
    ("mushroom", "熟蘑菇", "cooked", "28", "3.6", "5.3", "0.5", ("蘑菇", "口蘑")),
    ("edamame", "熟毛豆", "cooked", "121", "11.9", "8.9", "5.2", ("毛豆", "青豆")),
    ("almond", "原味杏仁", "ready", "579", "21.2", "21.6", "49.9", ("杏仁", "坚果")),
    ("black-coffee", "黑咖啡", "ready", "2", "0.3", "0", "0", ("美式咖啡", "咖啡")),
)


EXERCISES = (
    (
        "dumbbell-goblet-squat",
        "哑铃高脚杯深蹲",
        "squat",
        "dumbbell",
        "beginner",
        ("quadriceps", "gluteus"),
        ("core",),
        ("双手托住哑铃贴近胸前，双脚自然站稳", "髋膝同步下沉，脚掌压地站起"),
        ("高脚杯深蹲", "壶式哑铃深蹲"),
    ),
    (
        "dumbbell-romanian-deadlift",
        "哑铃罗马尼亚硬拉",
        "hinge",
        "dumbbell",
        "beginner",
        ("hamstrings", "gluteus"),
        ("back", "core"),
        ("哑铃置于大腿前侧，膝盖微屈", "髋部后移至腿后侧拉伸，再夹臀站直"),
        ("哑铃RDL", "哑铃直腿硬拉"),
    ),
    (
        "dumbbell-bench-press",
        "哑铃平板卧推",
        "horizontal_push",
        "dumbbell",
        "beginner",
        ("chest",),
        ("triceps", "shoulders"),
        ("肩胛后缩平躺，哑铃位于胸部两侧", "前臂保持竖直，将哑铃推至胸部上方"),
        ("哑铃卧推", "平板哑铃推胸"),
    ),
    (
        "dumbbell-incline-press",
        "上斜哑铃卧推",
        "horizontal_push",
        "dumbbell",
        "intermediate",
        ("chest", "shoulders"),
        ("triceps",),
        ("将训练凳调至低上斜角，肩胛稳定贴凳", "沿上胸方向推起哑铃，顶端不碰撞"),
        ("上斜哑铃推胸",),
    ),
    (
        "dumbbell-fly",
        "哑铃飞鸟",
        "chest_fly",
        "dumbbell",
        "intermediate",
        ("chest",),
        ("shoulders",),
        ("双臂在胸部上方相对，肘部保持微屈", "以拥抱弧线打开和合拢双臂"),
        ("哑铃夹胸", "平板哑铃飞鸟"),
    ),
    (
        "dumbbell-one-arm-row",
        "单臂哑铃划船",
        "horizontal_pull",
        "dumbbell",
        "beginner",
        ("back",),
        ("biceps", "forearms"),
        ("支撑身体并保持背部平直，让哑铃自然下垂", "肘部贴近躯干向髋部拉，控制还原"),
        ("哑铃划船", "单手哑铃划船"),
    ),
    (
        "dumbbell-chest-supported-row",
        "胸托哑铃划船",
        "horizontal_pull",
        "dumbbell",
        "beginner",
        ("back",),
        ("biceps", "shoulders"),
        ("俯卧在上斜凳，双手自然下垂", "肩胛先后缩，再将肘部拉向身体两侧"),
        ("俯卧哑铃划船",),
    ),
    (
        "dumbbell-shoulder-press",
        "坐姿哑铃推举",
        "vertical_push",
        "dumbbell",
        "beginner",
        ("shoulders",),
        ("triceps", "core"),
        ("背部贴靠椅背，哑铃停在耳侧", "垂直推至头顶上方，控制下放"),
        ("哑铃肩推", "坐姿肩推"),
    ),
    (
        "dumbbell-lateral-raise",
        "哑铃侧平举",
        "shoulder_abduction",
        "dumbbell",
        "beginner",
        ("shoulders",),
        ("trapezius",),
        ("双臂自然下垂，肘部保持轻微弯曲", "向身体两侧抬至肩高，缓慢下放"),
        ("侧平举",),
    ),
    (
        "dumbbell-reverse-fly",
        "哑铃反向飞鸟",
        "horizontal_pull",
        "dumbbell",
        "intermediate",
        ("shoulders", "back"),
        ("trapezius",),
        ("髋部后移并稳定躯干，双臂垂向地面", "向两侧展开手臂并收紧肩胛"),
        ("俯身反向飞鸟", "哑铃后束飞鸟"),
    ),
    (
        "dumbbell-curl",
        "哑铃弯举",
        "curl",
        "dumbbell",
        "beginner",
        ("biceps",),
        ("forearms",),
        ("上臂贴近身体，掌心朝前握住哑铃", "保持肘部位置不动，屈肘举起后慢放"),
        ("哑铃二头弯举",),
    ),
    (
        "dumbbell-hammer-curl",
        "锤式弯举",
        "curl",
        "dumbbell",
        "beginner",
        ("biceps", "forearms"),
        (),
        ("掌心相对握住哑铃，上臂保持稳定", "沿中立握姿屈肘，控制离心下放"),
        ("哑铃锤式弯举",),
    ),
    (
        "dumbbell-overhead-extension",
        "哑铃过顶臂屈伸",
        "elbow_extension",
        "dumbbell",
        "beginner",
        ("triceps",),
        ("core",),
        ("双手托住哑铃置于头顶，肘部朝前", "仅屈伸肘关节，让哑铃在头后上下移动"),
        ("哑铃颈后臂屈伸",),
    ),
    (
        "dumbbell-bulgarian-split-squat",
        "哑铃保加利亚分腿蹲",
        "lunge",
        "dumbbell",
        "intermediate",
        ("quadriceps", "gluteus"),
        ("hamstrings", "core"),
        ("后脚搭凳，前脚站在能稳定下蹲的位置", "垂直降低后膝，再以前脚发力站起"),
        ("保加利亚分腿蹲", "哑铃保加利亚蹲"),
    ),
    (
        "cable-seated-row",
        "绳索坐姿划船",
        "horizontal_pull",
        "cable",
        "beginner",
        ("back",),
        ("biceps", "forearms"),
        ("坐稳并保持脊柱中立，手柄自然前伸", "肩胛后缩后将手柄拉向腹部"),
        ("坐姿划船", "绳索划船"),
    ),
    (
        "cable-face-pull",
        "绳索面拉",
        "horizontal_pull",
        "cable",
        "beginner",
        ("shoulders", "back"),
        ("trapezius", "biceps"),
        ("绳索设在面部高度，拇指朝后握绳", "向眉眼位置拉开绳索并外旋肩部"),
        ("面拉", "绳索后束面拉"),
    ),
    (
        "cable-straight-arm-pulldown",
        "绳索直臂下压",
        "vertical_pull",
        "cable",
        "beginner",
        ("back",),
        ("triceps", "core"),
        ("双臂近乎伸直握杆，躯干轻微前倾", "用背部将手柄压向大腿并控制回升"),
        ("直臂下拉", "绳索直臂下拉"),
    ),
    (
        "cable-chest-fly",
        "绳索夹胸",
        "chest_fly",
        "cable",
        "beginner",
        ("chest",),
        ("shoulders",),
        ("滑轮与胸部同高，身体前后分腿站稳", "保持肘部微屈，双臂沿弧线在胸前合拢"),
        ("龙门架夹胸", "绳索飞鸟"),
    ),
    (
        "cable-low-to-high-fly",
        "绳索上斜夹胸",
        "chest_fly",
        "cable",
        "intermediate",
        ("chest",),
        ("shoulders",),
        ("滑轮置于低位，双手在身体两侧握柄", "沿斜上方弧线合拢至上胸前"),
        ("低位绳索夹胸", "上斜绳索飞鸟"),
    ),
    (
        "cable-triceps-pushdown",
        "绳索三头下压",
        "elbow_extension",
        "cable",
        "beginner",
        ("triceps",),
        ("forearms",),
        ("肘部固定在身体两侧，前臂握住绳索", "向下伸直肘部并在底端分开绳头"),
        ("三头下压", "绳索下压"),
    ),
    (
        "cable-overhead-extension",
        "绳索过顶臂屈伸",
        "elbow_extension",
        "cable",
        "intermediate",
        ("triceps",),
        ("core",),
        ("背对滑轮分腿站稳，绳索置于头后", "固定上臂后向前上方伸直肘部"),
        ("绳索颈后臂屈伸",),
    ),
    (
        "cable-curl",
        "绳索弯举",
        "curl",
        "cable",
        "beginner",
        ("biceps",),
        ("forearms",),
        ("面对低位滑轮站稳，上臂贴近身体", "保持肘部固定，将手柄弯举至胸前"),
        ("绳索二头弯举",),
    ),
    (
        "cable-lateral-raise",
        "绳索侧平举",
        "shoulder_abduction",
        "cable",
        "beginner",
        ("shoulders",),
        ("trapezius",),
        ("单手握低位手柄，身体保持直立", "手臂向侧方抬至肩高后缓慢还原"),
        ("单臂绳索侧平举",),
    ),
    (
        "cable-glute-kickback",
        "绳索臀部后踢",
        "hip_extension",
        "cable",
        "beginner",
        ("gluteus",),
        ("hamstrings", "core"),
        ("脚踝连接低位拉索，双手扶稳器械", "骨盆保持稳定，将工作腿向后伸展"),
        ("绳索后踢", "绳索臀踢"),
    ),
    (
        "cable-hip-abduction",
        "绳索髋外展",
        "hip_abduction",
        "cable",
        "beginner",
        ("gluteus",),
        ("core",),
        ("脚踝连接低位拉索，支撑腿微屈", "工作腿向身体侧方抬起，骨盆保持水平"),
        ("绳索侧抬腿",),
    ),
    (
        "cable-wood-chop",
        "绳索伐木",
        "rotation",
        "cable",
        "intermediate",
        ("core",),
        ("shoulders", "gluteus"),
        ("侧对高位滑轮站稳，双手握住手柄", "躯干与髋部协同旋转，将手柄斜拉向对侧髋部"),
        ("高位伐木", "绳索转体"),
    ),
    (
        "cable-kneeling-crunch",
        "跪姿绳索卷腹",
        "core",
        "cable",
        "beginner",
        ("core",),
        ("hip_flexors",),
        ("跪在高位滑轮前，将绳索置于头部两侧", "保持髋部稳定，用腹部将肋骨卷向骨盆"),
        ("绳索卷腹",),
    ),
    (
        "bodyweight-push-up",
        "标准俯卧撑",
        "horizontal_push",
        "bodyweight",
        "beginner",
        ("chest",),
        ("triceps", "shoulders", "core"),
        ("双手略宽于肩，身体从头到脚保持直线", "胸部向地面下降，再推回起始位置"),
        ("俯卧撑", "伏地挺身"),
    ),
    (
        "bodyweight-pull-up",
        "引体向上",
        "vertical_pull",
        "bodyweight",
        "intermediate",
        ("back",),
        ("biceps", "forearms"),
        ("全握单杠并让肩胛稳定下沉", "肘部向身体两侧下拉，胸部靠近单杠"),
        ("正手引体",),
    ),
    (
        "bodyweight-squat",
        "徒手深蹲",
        "squat",
        "bodyweight",
        "beginner",
        ("quadriceps", "gluteus"),
        ("core", "hamstrings"),
        ("双脚自然站立，脚尖与膝盖方向一致", "髋膝同步下沉，脚掌压地站起"),
        ("自重深蹲", "空手深蹲"),
    ),
    (
        "bodyweight-plank",
        "平板支撑",
        "core",
        "bodyweight",
        "beginner",
        ("core",),
        ("shoulders", "gluteus"),
        ("前臂撑地，肘部位于肩部正下方", "收紧腹部和臀部，保持身体呈直线"),
        ("前臂平板支撑",),
    ),
    (
        "bodyweight-glute-bridge",
        "臀桥",
        "hip_extension",
        "bodyweight",
        "beginner",
        ("gluteus",),
        ("hamstrings", "core"),
        ("仰卧屈膝，双脚踩稳地面", "收紧臀部抬起髋部，避免腰部过度后仰"),
        ("自重臀桥",),
    ),
    (
        "bodyweight-reverse-lunge",
        "反向弓步蹲",
        "lunge",
        "bodyweight",
        "beginner",
        ("quadriceps", "gluteus"),
        ("hamstrings", "core"),
        ("站直后单腿向后迈出，前脚踩稳", "垂直降低后膝，再以前脚发力回到站姿"),
        ("后撤弓步", "反向箭步蹲"),
    ),
    (
        "machine-chest-press",
        "坐姿推胸机",
        "horizontal_push",
        "machine",
        "beginner",
        ("chest",),
        ("triceps", "shoulders"),
        ("调整座椅让手柄与胸部同高，肩胛贴稳靠垫", "向前推至手臂接近伸直，再控制还原"),
        ("器械推胸", "坐姿胸推"),
    ),
    (
        "machine-seated-row",
        "坐姿划船机",
        "horizontal_pull",
        "machine",
        "beginner",
        ("back",),
        ("biceps", "forearms"),
        ("胸部或背部贴稳支撑，双手握住手柄", "肩胛后缩并将肘部拉向身体后方"),
        ("器械划船",),
    ),
    (
        "machine-shoulder-press",
        "肩推机",
        "vertical_push",
        "machine",
        "beginner",
        ("shoulders",),
        ("triceps",),
        ("调整座椅让手柄位于耳侧，背部贴稳靠垫", "向上推至手臂接近伸直，控制下放"),
        ("器械肩推", "坐姿推肩机"),
    ),
    (
        "machine-assisted-pull-up",
        "辅助引体向上",
        "vertical_pull",
        "machine",
        "beginner",
        ("back",),
        ("biceps", "forearms"),
        ("选择合适辅助重量，双膝或双脚稳定在踏板上", "肩胛下沉并将胸部拉向握把"),
        ("辅助引体", "器械引体向上"),
    ),
)


def upgrade() -> None:
    foods = sa.table(
        "foods",
        sa.column("id", sa.Uuid()),
        sa.column("owner_user_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("brand", sa.String()),
        sa.column("region", sa.String()),
        sa.column("state", sa.String()),
    )
    food_versions = sa.table(
        "food_versions",
        sa.column("id", sa.Uuid()),
        sa.column("food_id", sa.Uuid()),
        sa.column("version", sa.Integer()),
        sa.column("basis_amount_g", sa.Numeric()),
        sa.column("kcal", sa.Numeric()),
        sa.column("protein_g", sa.Numeric()),
        sa.column("carbs_g", sa.Numeric()),
        sa.column("fat_g", sa.Numeric()),
        sa.column("source", sa.String()),
        sa.column("confidence", sa.String()),
    )
    food_aliases = sa.table(
        "food_aliases",
        sa.column("id", sa.Uuid()),
        sa.column("food_id", sa.Uuid()),
        sa.column("alias", sa.String()),
    )
    exercises = sa.table(
        "exercises",
        sa.column("id", sa.Uuid()),
        sa.column("owner_user_id", sa.Uuid()),
        sa.column("name_zh", sa.String()),
        sa.column("movement_pattern", sa.String()),
        sa.column("equipment", sa.String()),
        sa.column("difficulty", sa.String()),
        sa.column("instructions", postgresql.JSONB()),
        sa.column("breathing", postgresql.JSONB()),
        sa.column("common_errors", postgresql.JSONB()),
        sa.column("safety_notes", postgresql.JSONB()),
        sa.column("notes", sa.String()),
    )
    exercise_aliases = sa.table(
        "exercise_aliases",
        sa.column("id", sa.Uuid()),
        sa.column("exercise_id", sa.Uuid()),
        sa.column("alias", sa.String()),
        sa.column("normalized_alias", sa.String()),
    )
    exercise_muscles = sa.table(
        "exercise_muscles",
        sa.column("exercise_id", sa.Uuid()),
        sa.column("muscle_code", sa.String()),
        sa.column("role", sa.String()),
    )

    op.bulk_insert(
        foods,
        [
            {
                "id": _id("food", slug),
                "owner_user_id": None,
                "name": name,
                "brand": None,
                "region": "CN",
                "state": state,
            }
            for slug, name, state, *_ in FOODS
        ],
    )
    op.bulk_insert(
        food_versions,
        [
            {
                "id": _id("food-version", slug),
                "food_id": _id("food", slug),
                "version": 1,
                "basis_amount_g": Decimal("100"),
                "kcal": Decimal(kcal),
                "protein_g": Decimal(protein),
                "carbs_g": Decimal(carbs),
                "fat_g": Decimal(fat),
                "source": "curated_cn_reference_v1",
                "confidence": "medium",
            }
            for slug, _, _, kcal, protein, carbs, fat, _ in FOODS
        ],
    )
    op.bulk_insert(
        food_aliases,
        [
            {
                "id": _id("food-alias", f"{slug}:{index}"),
                "food_id": _id("food", slug),
                "alias": alias,
            }
            for slug, *_, aliases in FOODS
            for index, alias in enumerate(aliases, start=1)
        ],
    )

    op.bulk_insert(
        exercises,
        [
            {
                "id": _id("exercise", slug),
                "owner_user_id": None,
                "name_zh": name,
                "movement_pattern": pattern,
                "equipment": equipment,
                "difficulty": difficulty,
                "instructions": list(instructions),
                "breathing": ["还原阶段吸气", "发力阶段呼气"],
                "common_errors": ["借助惯性完成动作", "超出可稳定控制的动作幅度"],
                "safety_notes": [
                    "先用轻重量熟悉轨迹，保持关节自然对齐",
                    "出现锐痛、麻木或明显不适时立即停止",
                ],
                "notes": "动态解剖图用于理解发力区域和关节轨迹，不替代现场动作指导。",
            }
            for (
                slug,
                name,
                pattern,
                equipment,
                difficulty,
                _,
                _,
                instructions,
                _,
            ) in EXERCISES
        ],
    )
    op.bulk_insert(
        exercise_aliases,
        [
            {
                "id": _id("exercise-alias", f"{slug}:{index}"),
                "exercise_id": _id("exercise", slug),
                "alias": alias,
                "normalized_alias": alias.strip().casefold(),
            }
            for slug, *_, aliases in EXERCISES
            for index, alias in enumerate(aliases, start=1)
        ],
    )
    op.bulk_insert(
        exercise_muscles,
        [
            {
                "exercise_id": _id("exercise", slug),
                "muscle_code": muscle,
                "role": role,
            }
            for slug, _, _, _, _, primary, secondary, _, _ in EXERCISES
            for role, muscles in (("primary", primary), ("secondary", secondary))
            for muscle in muscles
        ],
    )


def downgrade() -> None:
    food_ids = ", ".join(f"'{_id('food', item[0])}'" for item in FOODS)
    exercise_ids = ", ".join(f"'{_id('exercise', item[0])}'" for item in EXERCISES)
    op.execute(f"DELETE FROM foods WHERE id IN ({food_ids})")
    op.execute(f"DELETE FROM exercises WHERE id IN ({exercise_ids})")
