"""Expand Smith/machine exercises with complete guidance and anatomy metadata."""

from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, insert

revision = "f8c5d3b0a721"
down_revision = "e7f4c2a9b610"
branch_labels = None
depends_on = None

NAMESPACE = UUID("aafcebd3-aa88-47e3-9390-9ebdf3a7fe9f")


def exercise_id(slug: str) -> UUID:
    return uuid5(NAMESPACE, f"nxtrep:exercise:{slug}")


def entry(slug, name, equipment, pattern, primary, secondary, steps, errors, safety, aliases):
    return {
        "id": exercise_id(slug),
        "name_zh": name,
        "equipment": equipment,
        "movement_pattern": pattern,
        "difficulty": "intermediate" if equipment in {"smith_machine", "barbell"} else "beginner",
        "primary": primary,
        "secondary": secondary,
        "instructions": steps,
        "breathing": ("还原阶段自然吸气，保持躯干稳定。", "发力阶段呼气，避免长时间憋气。"),
        "common_errors": errors,
        "safety_notes": safety,
        "aliases": aliases,
    }


# Names, equipment and movement patterns are kept distinct even when a gym uses
# the same frame for several exercises. The app renders anatomy from this data.
EXERCISES = (
    entry(
        "smith-flat-press",
        "史密斯平板卧推",
        "smith_machine",
        "horizontal_push",
        ("chest",),
        ("triceps", "shoulders"),
        (
            "将平凳放在导轨中央，空杆试推，调整凳位使下放时横杆对准胸部。",
            "双脚踩稳，肩胛稳定贴凳，握距以底部前臂接近竖直为准。",
            "解锁后控制下放至舒适深度，再沿导轨推起，完成后重新挂牢。",
        ),
        ("凳位不合适使横杆压向颈部。", "肩膀前顶、臀部离凳或借胸部反弹。"),
        (
            "先用空杆确定轨迹，并将安全限位放在最低可控位置下方。",
            "固定轨迹不适合肩部时调整凳位或停止，不勉强压低。",
        ),
        ("史密斯卧推", "史密斯平板推胸", "Smith bench press"),
    ),
    entry(
        "smith-incline-press",
        "史密斯上斜推胸",
        "smith_machine",
        "horizontal_push",
        ("chest",),
        ("shoulders", "triceps"),
        (
            "将靠背调到约30度低上斜，凳子放在导轨中央，空杆检查上胸前方的轨迹。",
            "脚掌踩稳，肩胛贴凳，握距以底部前臂接近竖直为准。",
            "解锁后将横杆缓慢降向上胸前方，在肩部舒适范围内推回，结束后挂牢。",
        ),
        ("靠背过陡而把上斜推胸变成推肩。", "下放到颈部、肩膀前顶或下背过度拱起。"),
        (
            "先确认安全限位和挂钩方向；倾斜导轨的朝向遵循该器械说明。",
            "不追求横杆必须碰胸，保持肩关节可控。",
        ),
        ("史密斯上斜卧推", "上斜史密斯卧推", "史密斯机上斜推胸", "Smith incline bench press"),
    ),
    entry(
        "smith-decline-press",
        "史密斯下斜卧推",
        "smith_machine",
        "horizontal_push",
        ("chest",),
        ("triceps", "shoulders"),
        (
            "使用带腿部固定装置的下斜凳，将凳位与导轨对齐并先空杆检查。",
            "固定双腿、肩胛贴凳，横杆下放方向对准胸部下方。",
            "控制下降至肩部舒适范围，沿导轨推回并重新挂牢。",
        ),
        ("使用没有固定装置的凳子导致身体下滑。", "握距过宽或以反弹代替发力。"),
        (
            "确认凳子锁定、安全限位与腿部固定可靠。",
            "上下凳或装卸片前先挂牢横杆，初次使用请现场人员协助。",
        ),
        ("史密斯下斜推胸", "下斜史密斯卧推", "Smith decline press"),
    ),
    entry(
        "smith-seated-shoulder-press",
        "史密斯坐姿推肩",
        "smith_machine",
        "vertical_push",
        ("shoulders",),
        ("triceps",),
        (
            "将靠背调至接近直立，凳子放在导轨中央，空杆确定横杆在面部前方的轨迹。",
            "脚掌踩稳、背部贴凳，握杆使前臂在底部接近竖直。",
            "从下巴至肩部附近的舒适高度推向头顶，控制回落，再挂牢横杆。",
        ),
        ("为绕过脸部而后仰、塌腰或伸颈。", "把横杆下放到颈后，或下降超出肩部活动范围。"),
        (
            "设置安全限位，空杆确认横杆不会碰到脸部。",
            "采用颈前轨迹；无法舒适完成时调整凳位，不强行迎合导轨。",
        ),
        ("史密斯推肩", "史密斯肩推", "史密斯推举", "史密斯坐姿推举", "Smith shoulder press"),
    ),
    entry(
        "smith-squat",
        "史密斯深蹲",
        "smith_machine",
        "squat",
        ("quadriceps", "gluteus"),
        ("hamstrings", "core"),
        (
            "将横杆放在上背肌肉处，双脚站在能保持全脚掌受力的位置。",
            "先空杆调整脚位和限位，收紧躯干后解锁，髋膝协同屈曲。",
            "下降到骨盆和足底仍可稳定控制的深度，再蹬地站起并挂牢。",
        ),
        ("膝盖内扣、脚跟抬起或底部骨盆明显卷起。", "把所有人的脚位和深度设成相同。"),
        (
            "安全限位应能在无法起身时接住横杆。",
            "根据导轨倾角和个人活动范围调整站位，不依靠导轨硬压深度。",
        ),
        ("史密斯机深蹲", "Smith squat"),
    ),
    entry(
        "smith-romanian-deadlift",
        "史密斯罗马尼亚硬拉",
        "smith_machine",
        "hinge",
        ("hamstrings", "gluteus"),
        ("back", "core"),
        (
            "双脚站稳，横杆位于大腿前方，膝盖保持轻微弯曲。",
            "臀部向后移动，让横杆贴近腿部沿导轨下降，背部保持自然中立。",
            "腿后侧出现拉伸且躯干仍可控时停止下降，伸髋回到站姿。",
        ),
        ("用弯腰代替髋部后移。", "为了触地而继续降低横杆，或顶端过度后仰。"),
        ("从轻重量开始，按腿后侧柔韧性决定下降幅度。", "确保身体与导轨有足够空间，横杆不必落地。"),
        ("史密斯RDL", "史密斯罗马尼亚拉", "Smith Romanian deadlift"),
    ),
    entry(
        "smith-split-squat",
        "史密斯保加利亚分腿蹲",
        "smith_machine",
        "lunge",
        ("quadriceps", "gluteus"),
        ("hamstrings", "core"),
        (
            "后脚放在稳固矮凳上，前脚踩稳，横杆置于上背。",
            "先空杆调整前后距离，身体下沉时让前膝顺着脚尖方向移动。",
            "以前脚蹬地站起，完成一侧后挂牢横杆再换侧。",
        ),
        ("过度依赖后脚发力。", "前脚站得过窄，下降时失去骨盆稳定。"),
        ("固定后脚支撑凳并设置限位，不站在不稳的软垫上。", "先熟悉徒手分腿蹲，再增加负重。"),
        ("史密斯保加利亚蹲", "史密斯分腿蹲", "Smith Bulgarian split squat"),
    ),
    entry(
        "smith-hip-thrust",
        "史密斯臀推",
        "smith_machine",
        "hip_thrust",
        ("gluteus",),
        ("hamstrings", "core"),
        (
            "用稳固凳支撑肩胛下缘，横杆加护垫放在髋部，双脚踩稳。",
            "调整凳位，使顶端膝盖约呈直角，横杆沿导轨移动时不拉扯身体。",
            "收紧腹部、抬髋至躯干与大腿接近一线，控制下降。",
        ),
        ("通过腰椎后仰抬高横杆。", "凳子滑动或横杆压在腹部。"),
        ("固定凳子并先试验挂钩和限位，确认能够安全退出。", "用护垫分散髋部压力，颈部保持自然。"),
        ("史密斯机臀推", "Smith hip thrust"),
    ),
    entry(
        "smith-standing-calf-raise",
        "史密斯站姿提踵",
        "smith_machine",
        "calf_raise",
        ("calves",),
        ("core",),
        (
            "横杆置于上背，前脚掌站在稳固防滑踏板上，身体保持直立。",
            "膝盖自然伸展但不顶死，缓慢抬高脚跟。",
            "顶端短暂停留，再控制脚跟下降至舒适拉伸位置。",
        ),
        ("借膝盖屈伸弹起重量。", "脚踝向内外翻或用快速反弹完成。"),
        ("踏板需稳固且足够宽，先用轻重量设置限位。", "保持可控幅度，不让脚跟突然下坠。"),
        ("史密斯提踵", "Smith calf raise"),
    ),
    entry(
        "machine-incline-chest-press",
        "上斜推胸机",
        "machine",
        "horizontal_push",
        ("chest",),
        ("shoulders", "triceps"),
        (
            "调整座椅，让把手位于上胸附近，背部贴靠垫，脚掌踩稳。",
            "握紧把手，保持手腕与前臂自然对齐。",
            "沿机器的斜上轨迹推起，控制回落至肩部舒适范围。",
        ),
        ("耸肩、塌腰或臀部离座。", "座椅过低，手柄起点明显高于肩部。"),
        ("先用轻重量检查轨迹，按器械标识调节起始位置。", "还原时不让配重片撞击。"),
        ("器械上斜推胸", "固定器械上斜推胸", "悍马上斜推胸", "Incline chest press machine"),
    ),
    entry(
        "machine-pec-deck",
        "蝴蝶机夹胸",
        "machine",
        "chest_fly",
        ("chest",),
        ("shoulders",),
        (
            "调节座椅，使肘部或把手接近胸部高度，背部贴垫。",
            "按机器设计握把或让前臂贴垫，肘部保持自然弯曲。",
            "双臂向胸前夹合，停顿后慢慢打开，不强拉到身后。",
        ),
        ("夹合时耸肩或向前探头。", "将起始位置调得过深，靠惯性甩动。"),
        ("起始位置以肩部舒适为准，不追求最大拉伸。", "夹合端不碰撞手柄或配重片。"),
        ("蝴蝶夹胸", "器械夹胸", "坐姿夹胸机", "Pec deck fly"),
    ),
    entry(
        "machine-reverse-pec-deck",
        "反向蝴蝶机飞鸟",
        "machine",
        "reverse_fly",
        ("shoulders",),
        ("back", "trapezius"),
        (
            "面朝靠垫坐稳，调整座椅让把手接近肩高，胸部轻贴垫。",
            "双手握把，肘部轻屈，肩膀保持下沉。",
            "双臂向两侧打开至与躯干接近一线，缓慢回到前方。",
        ),
        ("用躯干后仰带动把手。", "耸肩或把手拉到身体后方过远。"),
        ("先按机器标识切换到反向飞鸟位置并锁定。", "保持胸部支撑，选择能控制回程的重量。"),
        ("反向蝴蝶机", "器械后束飞鸟", "反向夹胸机", "Reverse pec deck"),
    ),
    entry(
        "machine-lateral-raise",
        "器械侧平举",
        "machine",
        "shoulder_abduction",
        ("shoulders",),
        ("trapezius",),
        (
            "调整座椅，将上臂靠在侧方垫上，肩关节对准器械转轴附近。",
            "保持躯干稳定、肘部自然弯曲，沿机器轨迹向两侧抬臂。",
            "抬至肩部舒适高度后缓慢还原。",
        ),
        ("耸肩顶起配重。", "身体左右摆动或猛压手柄。"),
        ("按器械标识调整座椅和臂垫，不以疼痛换取高度。", "还原时避免配重片突然落下。"),
        ("侧平举机", "固定器械侧平举", "Machine lateral raise"),
    ),
    entry(
        "machine-chest-supported-row",
        "胸托划船机",
        "machine",
        "seated_row",
        ("back",),
        ("biceps", "shoulders"),
        (
            "调节座椅和胸垫，胸部贴垫时能舒适握到把手。",
            "脚掌踩稳，保持胸部支撑，把肘部拉向躯干两侧。",
            "短暂停留，再控制手柄前移，肩膀不被重量猛拉。",
        ),
        ("离开胸垫后仰借力。", "过度耸肩或只用手腕弯曲拉动。"),
        ("保持胸垫压力适中，呼吸顺畅。", "选择能在回程保持控制的重量。"),
        ("器械胸托划船", "悍马划船", "Chest supported machine row"),
    ),
    entry(
        "machine-leg-press",
        "腿举机",
        "machine",
        "leg_press",
        ("quadriceps", "gluteus"),
        ("hamstrings",),
        (
            "背部和骨盆贴靠垫，双脚放在踏板中部，脚尖与膝盖方向一致。",
            "确认限位后解锁，缓慢屈髋屈膝，在骨盆不卷起的深度停下。",
            "全脚掌蹬动踏板，伸腿但不猛顶膝关节，再控制还原。",
        ),
        ("降得过深导致下背离垫。", "膝盖内扣、用手推膝或顶端锁死膝盖。"),
        (
            "使用前熟悉锁定杆和安全限位；全程脚掌接触踏板。",
            "配重与踏板角度因机型不同，避免直接比较不同机器的重量。",
        ),
        ("器械腿举", "45度腿举", "倒蹬机", "蹬腿机", "Leg press"),
    ),
    entry(
        "machine-hack-squat",
        "哈克深蹲机",
        "machine",
        "squat",
        ("quadriceps", "gluteus"),
        ("hamstrings",),
        (
            "肩部放在肩垫下，背部贴垫，双脚踩稳踏板。",
            "先轻推解锁，收紧躯干后缓慢屈膝下降。",
            "在脚跟、骨盆仍稳定的位置停下，蹬踏板站起并保持膝盖自然。",
        ),
        ("脚跟抬起或膝盖向内塌。", "底部借反弹起身、顶端猛锁膝。"),
        ("先确认安全挡位及锁定方式。", "深度按个人活动范围决定，不让下背离垫。"),
        ("哈克深蹲", "哈克蹲", "Hack squat"),
    ),
    entry(
        "machine-leg-extension",
        "坐姿腿屈伸",
        "machine",
        "knee_extension",
        ("quadriceps",),
        (),
        (
            "调整靠背，使膝关节与机器转轴对齐，滚垫放在脚踝上方的小腿前侧。",
            "臀部和背部贴垫，双手握把，伸膝抬起滚垫。",
            "在舒适伸展位置停顿，再缓慢屈膝还原。",
        ),
        ("用抬臀或身体后仰甩起重量。", "滚垫压在脚背，或顶端猛踢。"),
        ("按器械标识调节活动范围，膝部不适时缩小幅度并停止加重。", "轻重量起步，不让配重片撞击。"),
        ("腿屈伸", "腿伸展", "坐姿腿伸", "踢腿机", "Leg extension"),
    ),
    entry(
        "machine-seated-leg-curl",
        "坐姿腿弯举",
        "machine",
        "seated_leg_curl",
        ("hamstrings",),
        ("calves",),
        (
            "调整靠背和转轴，使膝盖对齐转轴；小腿后侧放在滚垫上。",
            "压好大腿固定垫，背部贴垫，双手握把。",
            "屈膝将脚跟拉向座椅下方，保持大腿稳定，再缓慢伸膝还原。",
        ),
        ("大腿固定不牢，靠抬臀完成。", "身体前后摆动或让脚踝承担过多压力。"),
        ("固定垫压在大腿上而不是膝盖上。", "根据膝关节舒适度调整起始伸膝角度。"),
        ("坐姿腿屈曲", "坐式腿弯举", "Seated leg curl"),
    ),
    entry(
        "machine-lying-leg-curl",
        "俯卧腿弯举",
        "machine",
        "lying_leg_curl",
        ("hamstrings",),
        ("calves",),
        (
            "俯卧在垫上，膝关节对齐机器转轴，滚垫位于脚踝上方。",
            "双手握把，髋部贴垫，屈膝把脚跟带向臀部。",
            "在髋部不抬起的范围内停顿，再控制伸膝还原。",
        ),
        ("抬臀、塌腰来增加弯举幅度。", "下放时完全失去控制或猛踢滚垫。"),
        (
            "先调整滚垫与膝盖位置，避免滚垫压住跟腱。",
            "腹部和骨盆保持支撑，不用大重量迫使下背代偿。",
        ),
        ("卧式腿弯举", "俯卧腿屈曲", "Lying leg curl"),
    ),
    entry(
        "machine-hip-abduction",
        "坐姿髋外展",
        "machine",
        "seated_hip_abduction",
        ("gluteus",),
        (),
        (
            "坐稳并贴住靠背，将双腿外侧放在垫上，脚放在支撑处。",
            "握住把手，保持骨盆稳定，双膝向两侧打开。",
            "在可控范围内停顿，再缓慢向内还原。",
        ),
        ("用躯干左右摆动或弹动膝盖。", "为了张得更开而失去骨盆支撑。"),
        ("先调整舒适的起始宽度，按机型确认内外展模式。", "垫面接触大腿外侧，避免直接压膝关节。"),
        ("髋外展机", "器械髋外展", "大腿外展机", "Hip abduction machine"),
    ),
    entry(
        "machine-hip-adduction",
        "坐姿髋内收",
        "machine",
        "seated_hip_adduction",
        ("adductors",),
        (),
        (
            "坐稳并贴靠背，将大腿内侧贴在垫上，选择舒适的张开角度。",
            "保持骨盆稳定，双腿缓慢向中间夹合。",
            "夹合后停顿，再控制双腿向两侧打开。",
        ),
        ("起始角度过大，内侧被强行拉伸。", "靠冲击夹合或用手帮助压腿。"),
        (
            "从较小开度和轻重量开始，避免腹股沟过度牵拉。",
            "确认机器处于内收模式，回程不放任双腿被拉开。",
        ),
        ("髋内收机", "器械髋内收", "大腿内收机", "夹腿机", "Hip adduction machine"),
    ),
    entry(
        "machine-seated-calf-raise",
        "坐姿提踵机",
        "machine",
        "seated_calf_raise",
        ("calves",),
        (),
        (
            "坐稳，将膝部垫放在大腿远端，前脚掌踩住踏板。",
            "解除限位后保持膝盖位置稳定，缓慢抬起脚跟。",
            "顶端停顿，再控制脚跟下降至舒适拉伸位。",
        ),
        ("用身体上下弹动配重。", "脚踝内翻或外翻、脚掌从踏板滑开。"),
        ("膝垫不直接压在膝盖骨上，踏板保持干燥防滑。", "先熟悉限位杆，再增加重量。"),
        ("坐姿提踵", "器械坐姿提踵", "Seated calf raise"),
    ),
    entry(
        "machine-hip-thrust",
        "臀推机",
        "machine",
        "hip_thrust",
        ("gluteus",),
        ("hamstrings", "core"),
        (
            "按机型调整靠垫与髋部护垫或束带，双脚踩稳踏板。",
            "固定肩背，收紧腹部，将髋部向上推起。",
            "至躯干与大腿接近一线时停顿，再缓慢下降。",
        ),
        ("抬头、塌腰来增加顶端高度。", "护垫或束带压在腹部而非髋部。"),
        ("先检查束带扣和限位是否牢固。", "不同机型的上机方式不同，按机身标识操作。"),
        ("器械臀推", "固定器械臀推", "臀桥机", "Hip thrust machine"),
    ),
    entry(
        "machine-preacher-curl",
        "器械牧师凳弯举",
        "machine",
        "curl",
        ("biceps",),
        ("forearms",),
        (
            "调整座椅，上臂贴在支撑垫上，肘部对齐机器转轴附近。",
            "握住把手，保持上臂稳定，屈肘把把手拉向肩部。",
            "短暂停顿，缓慢伸肘还原，不让肘关节被猛拉直。",
        ),
        ("抬肩或上臂离垫。", "手腕过度弯曲，借身体前后摇晃带动。"),
        ("以肘部舒适的范围为准，底部保留控制。", "手掌握稳，避免配重突然落下。"),
        ("弯举机", "器械二头弯举", "牧师凳弯举机", "Machine preacher curl"),
    ),
    entry(
        "machine-triceps-extension",
        "器械三头臂屈伸",
        "machine",
        "elbow_extension",
        ("triceps",),
        (),
        (
            "调节座椅，将上臂放在支撑垫上，肘部对齐机器转轴。",
            "握稳把手、保持上臂位置，伸肘将把手推开。",
            "在肘部自然伸展处停下，再缓慢屈肘回位。",
        ),
        ("靠耸肩或躯干前倾压动重量。", "顶端猛锁肘，回程上臂离垫。"),
        ("按机型标识确认推压方向及肘垫位置。", "肘关节不适时停止，不强行达到机器最大行程。"),
        ("三头肌训练机", "器械臂屈伸", "三头伸展机", "Triceps extension machine"),
    ),
    entry(
        "machine-abdominal-crunch",
        "器械卷腹",
        "machine",
        "seated_crunch",
        ("core",),
        (),
        (
            "按机型调整座椅和胸垫或把手，脚放稳，骨盆保持支撑。",
            "以肋骨靠近骨盆的方式卷起躯干，手臂只用于固定。",
            "短暂停顿，再控制躯干展开到自然位置。",
        ),
        ("用手臂猛拉，或只在髋部折叠。", "还原时过度后仰、抬头牵拉颈部。"),
        ("轻重量起步，保持颈部自然，发力时呼气。", "只在可控范围内卷腹，不让配重拉扯下背。"),
        ("卷腹机", "坐姿卷腹机", "腹肌训练机", "Machine abdominal crunch"),
    ),
    entry(
        "barbell-romanian-deadlift",
        "杠铃罗马尼亚硬拉",
        "barbell",
        "hinge",
        ("hamstrings", "gluteus"),
        ("back", "core"),
        (
            "站稳握杆，横杆在大腿前方，膝盖微屈，收紧腹部。",
            "臀部后移，横杆贴近腿部下降，脊柱保持自然。",
            "腿后侧拉伸而背部仍稳定时停下，蹬地伸髋站直。",
        ),
        ("将动作做成深蹲，膝盖不断前移。", "弓背追求触地，或顶端向后折腰。"),
        ("先学会髋铰链，使用能控制离心阶段的重量。", "下降幅度因人而异，横杆无需落地。"),
        ("杠铃RDL", "罗马尼亚硬拉", "Romanian deadlift"),
    ),
    entry(
        "barbell-incline-bench-press",
        "上斜杠铃卧推",
        "barbell",
        "horizontal_push",
        ("chest",),
        ("shoulders", "triceps"),
        (
            "将凳背调至约30度低上斜，调整杠架和保护杆，双脚踩稳。",
            "肩胛贴凳，取杆后让横杆位于上胸上方。",
            "控制横杆下降至上胸前方的舒适位置，再推回并稳妥回架。",
        ),
        ("凳背过陡、肩膀前顶。", "横杆压向颈部或用胸部弹起重量。"),
        ("使用保护杆，较大重量时安排保护者。", "手腕与前臂保持对齐，避免强压肩部。"),
        ("杠铃上斜卧推", "上斜杠铃推胸", "Incline barbell bench press"),
    ),
    entry(
        "barbell-hip-thrust",
        "杠铃臀推",
        "barbell",
        "hip_thrust",
        ("gluteus",),
        ("hamstrings", "core"),
        (
            "肩胛下缘靠在稳固凳边，横杆加护垫放在髋部，双脚踩稳。",
            "收紧腹部、下巴轻收，推动髋部向上。",
            "顶端躯干和大腿接近一线，缓慢下降，避免腰部过度后仰。",
        ),
        ("用甩头或腰椎伸展代替伸髋。", "脚位过远或过近，凳子向后滑动。"),
        ("凳子需防滑固定，装片两侧平衡。", "使用髋部护垫，装卸横杆前确认空间和退出路径。"),
        ("杠铃负重臀推", "Barbell hip thrust"),
    ),
)

# Retain the identity of the previous Smith entry, including pending cards.
SMITH_INCLINE_ID = exercise_id("smith-incline-press")
NEW_EXERCISES = tuple(row for row in EXERCISES if row["id"] != SMITH_INCLINE_ID)

FOUNDATION_CONTENT = (
    (
        "10000000-0000-4000-8000-000000000001",
        (
            "将横杆放在上背肌肉处，双脚站稳，握紧横杆并收紧躯干。",
            "髋膝协同屈曲，膝盖顺着脚尖方向移动。",
            "下降到足底和脊柱仍稳定的位置，蹬地站起。",
        ),
        ("膝盖内扣或脚跟抬起。", "底部失去躯干控制，或起身时髋部先窜起。"),
        ("在深蹲架内设置保护杆，先用轻重量练习。", "深度按个人活动范围决定，不以疼痛换取幅度。"),
    ),
    (
        "10000000-0000-4000-8000-000000000002",
        (
            "双脚踩稳，肩胛贴凳，握距以底部前臂接近竖直为准。",
            "稳妥取杆，将横杆控制下降到胸部前方。",
            "保持肩背支撑，将横杆推起，结束时确认横杆放稳在挂钩上。",
        ),
        ("臀部离凳，肩膀前顶。", "横杆压向颈部或用胸部反弹。"),
        ("使用保护杆，较大重量时安排保护者。", "下降幅度以肩部舒适可控为准。"),
    ),
    (
        "10000000-0000-4000-8000-000000000003",
        (
            "横杆靠近小腿，双脚站稳，屈髋屈膝握杆并收紧躯干。",
            "保持横杆靠近身体，蹬地并伸髋站起。",
            "先向后移髋，再屈膝控制横杆回到地面，每次重新稳定。",
        ),
        ("横杆离腿过远，或拉起前背部明显弯曲。", "顶端过度后仰，以甩动代替控制。"),
        ("使用能保持脊柱自然的重量，从适合高度开始练习。", "回程控制重量，不让横杆压到脚部。"),
    ),
    (
        "10000000-0000-4000-8000-000000000004",
        (
            "握紧杠铃，膝盖微屈，髋部后移形成稳定俯身。",
            "保持躯干角度，将肘部拉向后方，使横杆靠近腹部。",
            "短暂停顿后缓慢伸臂，保持背部自然。",
        ),
        ("每次拉起都大幅起身甩动。", "耸肩或弓背，让手腕承担拉动。"),
        ("选择能稳定保持俯身的重量。", "下背无法维持舒适姿态时减重或改用胸托划船。"),
    ),
    (
        "10000000-0000-4000-8000-000000000005",
        (
            "双脚站稳，杠铃置于上胸前方，手腕与前臂保持对齐。",
            "收紧腹部和臀部，沿头部前方将横杆推向头顶。",
            "顶端身体自然站直，再控制横杆回到上胸前方。",
        ),
        ("过度后仰、肋骨外翻或用腿蹬起重量。", "让横杆远离身体，或撞到下巴。"),
        ("先用轻重量熟悉横杆绕过面部的轨迹。", "保持肩部舒适的范围，不采用颈后下降。"),
    ),
    (
        "10000000-0000-4000-8000-000000000006",
        (
            "坐稳并调整大腿固定垫，握住下拉杆，躯干仅轻微后倾。",
            "先让肩胛自然下沉，将肘部向身体两侧下拉，杆靠近上胸前方。",
            "控制手臂伸展回到头顶，不让配重猛拉肩部。",
        ),
        ("用身体大幅后仰甩动。", "向颈后下拉或耸肩硬拽。"),
        ("大腿固定牢靠，双脚保持支撑。", "动作在颈前完成，握距和幅度以肩部舒适为准。"),
    ),
)


def upgrade() -> None:
    exercises = sa.table(
        "exercises",
        sa.column("id", sa.Uuid()),
        sa.column("owner_user_id", sa.Uuid()),
        sa.column("name_zh", sa.String()),
        sa.column("equipment", sa.String()),
        sa.column("movement_pattern", sa.String()),
        sa.column("difficulty", sa.String()),
        *(
            sa.column(key, JSONB())
            for key in ("instructions", "breathing", "common_errors", "safety_notes")
        ),
    )
    aliases = sa.table(
        "exercise_aliases",
        sa.column("id", sa.Uuid()),
        sa.column("exercise_id", sa.Uuid()),
        sa.column("alias", sa.String()),
        sa.column("normalized_alias", sa.String()),
    )
    muscles = sa.table(
        "exercise_muscles",
        sa.column("exercise_id", sa.Uuid()),
        sa.column("muscle_code", sa.String()),
        sa.column("role", sa.String()),
    )
    content_keys = (
        "name_zh",
        "equipment",
        "movement_pattern",
        "difficulty",
        "instructions",
        "breathing",
        "common_errors",
        "safety_notes",
    )
    for row in EXERCISES:
        values = {
            key: list(row[key]) if isinstance(row[key], tuple) else row[key] for key in content_keys
        }
        statement = insert(exercises).values(id=row["id"], owner_user_id=None, **values)
        op.execute(
            statement.on_conflict_do_update(
                index_elements=["id"],
                set_=values,
                where=exercises.c.owner_user_id.is_(None),
            )
        )
        for alias in row["aliases"]:
            op.execute(
                insert(aliases)
                .values(
                    id=uuid5(NAMESPACE, f"nxtrep:exercise-alias:{row['id']}:{alias.casefold()}"),
                    exercise_id=row["id"],
                    alias=alias,
                    normalized_alias=alias.strip().casefold(),
                )
                .on_conflict_do_nothing(index_elements=["exercise_id", "normalized_alias"])
            )
        for role, group in (("primary", row["primary"]), ("secondary", row["secondary"])):
            for muscle in group:
                op.execute(
                    insert(muscles)
                    .values(
                        exercise_id=row["id"],
                        muscle_code=muscle,
                        role=role,
                    )
                    .on_conflict_do_nothing(index_elements=["exercise_id", "muscle_code"])
                )
    # Fill only genuinely blank official content; never alter custom exercises,
    # IDs, versions, existing nonempty descriptions or recorded set snapshots.
    for identifier, steps, errors, safety in FOUNDATION_CONTENT:
        for key, value in (
            ("instructions", steps),
            ("common_errors", errors),
            ("safety_notes", safety),
            (
                "breathing",
                ("还原或准备阶段自然吸气，保持躯干稳定。", "发力时呼气，避免长时间憋气。"),
            ),
        ):
            op.execute(
                exercises.update()
                .where(
                    exercises.c.id == UUID(identifier),
                    exercises.c.owner_user_id.is_(None),
                    exercises.c[key] == [],
                )
                .values({key: list(value)})
            )


def downgrade() -> None:
    # Catalog rows may already be referenced by workouts/plans or confirmations.
    # Keep stable IDs and user history when reverting the migration marker.
    pass
