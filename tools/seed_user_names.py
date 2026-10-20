"""Example: seed member preferred names for a group.

Copy this script, replace the placeholder group/user IDs and names with your
own members, then run it from the `bot/` directory:

    python ..\tools\seed_user_names.py
"""

from __future__ import annotations

import os

from storage.store import Store


GROUP_ID = int(os.environ.get("QWBOT_GROUP_ID", "123456789"))
PROFILES = {
    10001: "甲前辈",
    10002: "乙前辈",
    10003: "丙前辈",
    10004: "丁前辈",
    10005: "戊前辈",
}

RULE = (
    "群内称呼规则：无论原版樱还是黑樱，对群成员一律使用“短称+前辈”，例如“甲前辈”“乙前辈”。"
    "禁止使用“哥/姐/叔/姨/老师/学长/学姐/师兄/师姐/先生/小姐/老板”等后缀称呼群成员，也禁止“区/处”玩梗；"
    "昵称本身带这些后缀时，去掉后缀再加“前辈”（“阿明哥”→“阿明前辈”）。同一条回复不要重复称呼。"
)


def main() -> None:
    store = Store("../data/qwbot.sqlite3")
    for user_id, preferred_name in PROFILES.items():
        store.upsert_user_profile(
            GROUP_ID,
            user_id,
            preferred_name=preferred_name,
            notes="示例称呼；请替换成自己的群成员。",
        )
    store.add_memory(GROUP_ID, RULE, status="approved", source_kind="manual_user_instruction")
    print(f"seeded profiles={len(PROFILES)} group_id={GROUP_ID}")
    store.close()


if __name__ == "__main__":
    main()
