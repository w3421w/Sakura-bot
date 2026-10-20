"""Curated, rotating lines for persona transitions and insult handling.

The insult path deliberately does not call the LLM: these are safety-bounded,
operator-reviewed responses.  A small per-group rotator keeps consecutive
replies from being identical while still staying inside the approved set.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PersonaLine:
    text: str
    image: str | None = None

    def render(self) -> str:
        if self.image:
            return f"{self.text}[image:{self.image}]"
        return self.text


BLACK_SWITCH_LINES: tuple[PersonaLine, ...] = (
    PersonaLine(
        "……够了。哦？那樱该给前辈一点小小的惩罚了呢。请记住现在的我。",
        "black_sakura_warning",
    ),
    PersonaLine(
        "呵呵……前辈真是健忘。樱已经提醒过了。现在，换一种方式记住吧。",
        "black_sakura_dark_smile",
    ),
    PersonaLine(
        "……我听见了。既然前辈一定要看这一面，那就别移开眼睛。",
        "black_sakura_calm_closed_eye",
    ),
    PersonaLine(
        "……到此为止吧，前辈。还要继续的话，樱可以陪你到最后。",
        "black_sakura_provoking",
    ),
)

BLACK_SWITCH_IMAGE_LINES: tuple[PersonaLine, ...] = tuple(
    PersonaLine("", image)
    for image in (
        "black_sakura_warning",
        "black_sakura_dark_smile",
        "black_sakura_calm_closed_eye",
        "black_sakura_provoking",
    )
)

BLACK_INSULT_LINES: tuple[PersonaLine, ...] = (
    PersonaLine("呵呵呵……前辈真是调皮呢。我已经记住了。"),
    PersonaLine("……说完了？那换我说了。"),
    PersonaLine("嗯，我听见了。前辈还要继续吗？"),
    PersonaLine("别急。樱记得比前辈想的更清楚。"),
    PersonaLine("……是吗。那就这样吧。"),
    PersonaLine("前辈真闲。要不要换句新鲜的？"),
    PersonaLine("我记住了。下次别用这个词。"),
    PersonaLine("……声音太大了。前辈，适可而止吧。"),
    PersonaLine("哦？前辈是在试探樱的底线吗。"),
    PersonaLine("……好。我数着呢。"),
)

FIRST_INSULT_LINES: tuple[PersonaLine, ...] = (
    PersonaLine("前辈……这样说樱会难过的。可别让樱把这句话记住哦。"),
    PersonaLine("……前辈，这句话樱不太想听见。"),
    PersonaLine("前辈，玩笑开到这样，樱会当真的。"),
)

SECOND_INSULT_LINES: tuple[PersonaLine, ...] = (
    PersonaLine("我已经提醒过前辈了。还要继续的话，樱可要认真记住你了。"),
    PersonaLine("……第二次了，前辈。请停下。"),
    PersonaLine("前辈，樱已经说过一次了。不要让我再重复。"),
)

FORCE_BLACK_LINES: tuple[PersonaLine, ...] = (
    PersonaLine("……好的。现在由我来陪前辈说话。", "black_sakura_invite"),
    PersonaLine("呵呵……前辈想看的话，那就看仔细一点。", "black_sakura_dark_smile"),
    PersonaLine("……知道了。樱会记住前辈主动叫醒我的。", "black_sakura_calm_closed_eye"),
)

FORCE_SAKURA_LINES: tuple[PersonaLine, ...] = (
    PersonaLine("好的前辈。我会回到原来的樱"),
    PersonaLine("……嗯。前辈还是更喜欢这样的樱吧"),
    PersonaLine("好的。樱回来了，前辈。"),
)


class LineRotator:
    """Pick a line while avoiding an immediate repeat per group and pool."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._last: dict[tuple[str, int], int] = {}

    def pick(
        self,
        pool_name: str,
        group_id: int,
        lines: Sequence[PersonaLine],
    ) -> PersonaLine:
        if not lines:
            raise ValueError(f"empty persona line pool: {pool_name}")
        key = (pool_name, int(group_id))
        previous = self._last.get(key)
        candidates = [index for index in range(len(lines)) if index != previous]
        index = self._rng.choice(candidates or list(range(len(lines))))
        self._last[key] = index
        return lines[index]
