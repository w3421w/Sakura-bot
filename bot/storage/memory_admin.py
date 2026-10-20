"""Manual review CLI for group and user memories/profiles."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QWbot memory administration")
    parser.add_argument("--db", default="../data/qwbot.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("group_id", type=int)
    list_parser.add_argument("--status", choices=["pending", "approved", "rejected"])
    for command in ("approve", "reject"):
        item_parser = sub.add_parser(command)
        item_parser.add_argument("memory_id", type=int)
    add_parser = sub.add_parser("add")
    add_parser.add_argument("group_id", type=int)
    add_parser.add_argument("content")
    clear_parser = sub.add_parser("clear")
    clear_parser.add_argument("group_id", type=int)
    list_user = sub.add_parser("list-user")
    list_user.add_argument("group_id", type=int)
    list_user.add_argument("user_id", type=int)
    list_user.add_argument("--status", choices=["pending", "approved", "rejected"])
    add_user = sub.add_parser("add-user")
    add_user.add_argument("group_id", type=int)
    add_user.add_argument("user_id", type=int)
    add_user.add_argument("content")
    delete_user = sub.add_parser("delete-user")
    delete_user.add_argument("memory_id", type=int)
    for command in ("approve-user", "reject-user"):
        item_parser = sub.add_parser(command)
        item_parser.add_argument("memory_id", type=int)
    profile = sub.add_parser("profile")
    profile.add_argument("group_id", type=int)
    profile.add_argument("user_id", type=int)
    set_profile = sub.add_parser("set-profile")
    set_profile.add_argument("group_id", type=int)
    set_profile.add_argument("user_id", type=int)
    set_profile.add_argument("--nickname")
    set_profile.add_argument("--preferred-name")
    set_profile.add_argument("--role")
    set_profile.add_argument("--notes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db)
    store = Store(db_path)
    try:
        if args.command == "list":
            for memory_id, content, status, created_at in store.list_memories(args.group_id, args.status):
                print(f"ID={memory_id} 状态={status} 时间={created_at} 内容={content}")
        elif args.command == "approve":
            store.set_memory_status(args.memory_id, "approved")
        elif args.command == "reject":
            store.set_memory_status(args.memory_id, "rejected")
        elif args.command == "add":
            memory_id = store.add_memory(args.group_id, args.content, "approved")
            print(f"已新增记忆 ID={memory_id}")
        elif args.command == "clear":
            store.clear_memories(args.group_id)
            print("已清空该群长期记忆")
        elif args.command == "list-user":
            for memory_id, content, status, created_at in store.list_user_memories(
                args.group_id, args.user_id, status=args.status or "approved"
            ):
                print(f"ID={memory_id} 状态={status} 时间={created_at} 内容={content}")
        elif args.command == "add-user":
            memory_id = store.add_user_memory(args.group_id, args.user_id, args.content)
            print(f"已新增用户记忆 ID={memory_id}")
        elif args.command == "delete-user":
            store.delete_user_memory(args.memory_id)
            print("已删除用户记忆")
        elif args.command in {"approve-user", "reject-user"}:
            store.set_user_memory_status(
                args.memory_id,
                "approved" if args.command == "approve-user" else "rejected",
            )
        elif args.command == "profile":
            print(store.get_user_profile(args.group_id, args.user_id) or "暂无用户画像")
        elif args.command == "set-profile":
            store.upsert_user_profile(
                args.group_id,
                args.user_id,
                nickname=args.nickname,
                preferred_name=args.preferred_name,
                role=args.role,
                notes=args.notes,
            )
            print("已更新用户画像")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
