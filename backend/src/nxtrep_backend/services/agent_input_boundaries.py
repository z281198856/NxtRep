"""Conservative boundaries for single-intent shortcuts, not an intent classifier."""

import re


def has_additional_request(message: str) -> bool:
    """Leave additional actions/queries to the existing semantic planner."""
    return bool(re.search(
        r"另外|顺便|同时|以及|并且|然后|接着|还要|别忘了|"
        r"(?:再|并)(?:帮我|给我|为我)?(?:看|查|记录|保存|删|改|把|添加|设置|调整|制定|生成|创建|对比)|"
        r"[,，;；。]\s*(?:请|帮我|给我)?(?:查看|查询|记录|删除|修改|添加|设置|把|先看)",
        message,
    ))


def needs_semantic_task_input(message: str) -> bool:
    """Questions, hypotheticals and negation must not mutate a selected task first."""
    return has_additional_request(message) or bool(re.search(
        r"假如|如果|假设|例如|万一|为什么|如何|怎么|多少|是否|能否|会怎样|会怎么样|"
        r"查看|查询|看看|告诉我|吗|么|[?？]|不是|"
        r"(?:不要|别|先不|暂不|不必|不用|无需|不想|不能|不应)(?:再|给我|帮我|把)?"
        r"(?:改|调整|删|撤销|作废|移除|去掉|记录|记)",
        message,
    ))
