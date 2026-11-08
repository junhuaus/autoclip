# ruff: noqa: RUF001
"""Stage 19d: reviewer-style notes in customer-visible text are flagged."""

from __future__ import annotations

import pytest

from liveclip.domain.customer_delivery import (
    CUSTOMER_TEXT_WARNING_PATTERNS,
    CustomerText,
    customer_text_warnings,
    strong_customer_text_warnings,
)


@pytest.mark.parametrize(
    ("summary", "match"),
    [
        ("最后点明内口腔就在这个位置。“那口腔”“正强的”疑为转写错误。", "疑为"),
        ("唱久了嗓子也会累。“烟音”“拔喵”疑似误转写。", "疑似"),
        ("要求先改错误发声（ASR作“低音”，疑为“鼻音”）。", "ASR"),
        ("硬喊会喊出小结(字幕误作“小杰”)，并说小结要天天喊。", "字幕误作"),
        ("第五、六步紧接在后，但纳入后会超过时长上限，因此该单元在第四步的小结处结束。", "纳入后"),
        (
            "片段在这一难易对比完成后结束,下一句才转入鼻音与高音的关系。",
            "片段在这一难易对比完成后结束",
        ),
        ("连续课程片段：第四步讲真假声转换。", "课程片段"),
        ("这一单元以两类鼻音的难易对比收束，不包含后面鼻音影响高音的内容。", "这一单元"),
        ("两种技巧都在区间内讲解和示范。", "区间内"),
        ("从 cue 1049 开始到 cue 1130。", "cue"),
        ("开头在 900440 ms。", "900440 ms"),
        ("这个候选的边界偏晚。", "候选"),
    ],
)
def test_strong_reviewer_notes_are_flagged(summary: str, match: str) -> None:
    warnings = strong_customer_text_warnings(
        CustomerText(title="标题", hook="钩子", summary=summary)
    )
    assert warnings, summary
    assert warnings[0].field == "summary"
    assert summary[warnings[0].start : warnings[0].end] == warnings[0].match
    assert any(value.match == match for value in warnings)
    assert all(value.message for value in warnings)


@pytest.mark.parametrize(
    "summary",
    [
        "老师先说明气混就是气多一点并现场推气示范，最后以OK收束。",
        "示范后以“这就是假声，对吧”收束。",
        "并用婴儿发声作比解释小时候发声轻松的道理，最后简短收束。",
        "到第三步要学假声这种另一种形式的高音唱法。约93秒。",
    ],
)
def test_narration_is_advisory_only(summary: str) -> None:
    warnings = customer_text_warnings("标题", "钩子", summary)
    assert warnings and {value.kind for value in warnings} == {"narration"}
    assert strong_customer_text_warnings(CustomerText("标题", "钩子", summary)) == ()


@pytest.mark.parametrize(
    "summary",
    [
        "老师讲解找通道的第一步：自然打哈欠，感受口腔内部抬起，再用“闹”字体会位置。",
        "气混不是漏气，也不等于气声，老师用真声和气声对比示范两者的差别。",
        "学员现场演唱后，老师指出高音挤卡的原因在于通道没找到，并给出练习方法。",
        "唱歌学习路径分四步：真声、强混、假声，最后是真假声转换。",
        "老师提醒不要硬喊，声带需要放松，先在中音区建立正确的发声习惯。",
        "这一句的气息要稳，结尾不要收得太快。",
    ],
)
def test_ordinary_teaching_sentences_do_not_trip(summary: str) -> None:
    assert customer_text_warnings("找通道第一步", "打哈欠别硬撑", summary) == ()


def test_offsets_are_per_field_and_ordered() -> None:
    warnings = customer_text_warnings("疑为标题", "正常钩子", "以OK收束。疑似误转写。")
    assert [(value.field, value.kind, value.match) for value in warnings] == [
        ("title", "strong", "疑为"),
        ("summary", "narration", "以OK收束"),
        ("summary", "strong", "疑似"),
        ("summary", "strong", "误转写"),
    ]


def test_every_pattern_has_a_kind_and_message() -> None:
    assert CUSTOMER_TEXT_WARNING_PATTERNS
    for kind, pattern, message in CUSTOMER_TEXT_WARNING_PATTERNS:
        assert kind in {"strong", "narration"} and pattern.pattern and message
