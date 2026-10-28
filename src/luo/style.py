"""AI 味体检。

这里不做自动改写，只做检测：命中项用于调试（STYLE_DEBUG）和后续评估。
真正的约束在 persona 里；正则只是量尺，不是法官。
"""

from __future__ import annotations

import re

BANNED_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"作为一个\s*(AI|AI\s*助手|人工智能|语言模型|助手)", "自称AI"),
    (r"我(只)?是(一个)?\s*(AI|AI\s*助手|人工智能|语言模型|助手)", "自称AI"),
    (r"有什么(我)?(可以|能)帮(你|您)", "客服式提问"),
    (r"希望[^。！？\n]{0,12}(有(所)?帮助|帮到你)", "客服式结尾"),
    (
        r"(如果|要是)(你|您)(还有|有)?(任何)?(问题|需要)"
        r"[^。！？\n]{0,12}(随时|尽管|告诉我)",
        "客服式结尾",
    ),
    (r"很高兴(为|能)你(服务|解答)", "客服腔"),
    (r"首先[^。！？\n]{0,30}其次", "作文结构"),
    (r"总的来说|综上所述|总而言之", "总结腔"),
    (r"需要注意的是|值得注意的是", "提示腔"),
    (r"让我们[^。！？\n]{0,20}(来看看|开始|一起)", "讲解腔"),
    (r"根据(我的)?(记忆|记录)", "记忆腔"),
    (r"^\s*好的[，,]", "客服开头"),
    (r"^\s*当然可以", "客服开头"),
    (r"^\s*没问题[，,]", "客服开头"),
)

_COMPILED = tuple(
    (re.compile(pattern, re.MULTILINE), label) for pattern, label in BANNED_PATTERNS
)


def find_violations(text: str) -> list[str]:
    labels: list[str] = []
    for regex, label in _COMPILED:
        if regex.search(text) and label not in labels:
            labels.append(label)
    return labels
