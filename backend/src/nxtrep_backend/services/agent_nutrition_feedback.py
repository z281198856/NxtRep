"""Recognize corrections to a meal estimate without treating them as eaten grams."""

import re


def is_nutrition_estimate_feedback(message: str) -> bool:
    text = "".join(message.casefold().split())
    if len(text) > 160 or any(
        word in text
        for word in (
            "为什么",
            "多少",
            "怎么算",
            "怎么计算",
            "怎么来的",
            "吃什么",
            "推荐",
            "每天",
            "每日",
            "目标",
            "记住",
            "不要改",
            "不用改",
            "先别改",
            "别调整",
            "不调整",
        )
    ):
        return False
    nutrient = re.search(r"脂肪|蛋白质|碳水|热量", text)
    correction = re.search(
        r"偏高|偏低|太高|太低|高了|低了|估高|估低|不对|重估|重算|重新估|调整估算|"
        r"调低|调高|下调|上调|降一点|减一点|少一点|降低",
        text,
    )
    cooking = re.search(r"不是很油|不太油|没那么油|少油|清淡|水煮|清蒸|去皮|油炸", text)
    return bool(
        nutrient and correction or cooking and re.search(r"实际|其实|不是|我觉得|重估|重算", text)
    )
