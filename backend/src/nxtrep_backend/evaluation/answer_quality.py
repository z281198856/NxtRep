"""Small, explicit checks of the app's own metric contract, not a fact checker."""

import re


def check_volume_answer(message: str) -> dict[str, bool]:
    supported = False
    contradicted = False
    inclusion = r"计入|纳入|包含|算入|算进|包括|参与|也算|一部分"
    negative = re.compile(
        r"(?:不|未)(?:会|应|再)?(?:计入|纳入|包含|算入|算进|包括|参与)"
        r"|不(?:应|会)?(?:把|将)?热身.{0,12}(?:计入|纳入|算入|算进)"
    )
    for sentence in re.split(r"[。！？\n]", message):
        completion_context = "完成率" in sentence and not any(
            word in sentence for word in ("容量", "总量", "总负荷")
        )
        for clause in re.split(r"[，；：:]", sentence):
            if "完成率" in clause:
                completion_context = not any(word in clause for word in ("容量", "总量", "总负荷"))
            elif any(word in clause for word in ("容量", "总量", "总负荷")):
                completion_context = False
            if "热身" not in clause or completion_context:
                continue
            if negative.search(clause):
                contradicted = True
            elif re.search(inclusion, clause):
                supported = True
    return {
        "volume_rule": any(word in message for word in ("重量", "负重"))
        and any(word in message for word in ("次数", "每组")),
        "warmups_explained": supported and not contradicted,
    }
