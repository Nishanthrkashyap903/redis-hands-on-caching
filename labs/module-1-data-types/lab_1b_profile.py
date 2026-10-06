"""
Lab 1B — User profile hash (partial updates).

Cache key: app:user:<userId>
Counter key: app:user:next_id — INCR assigns a new unique user id on create.

Commands:
  create       — INCR next_id, HSET name, email, login_count=0
  set-name     — HSET name only
  set-email    — HSET email only
  show         — HGETALL for user id
  bump-login   — HINCRBY login_count 1
"""

import argparse
import os
import sys

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
USER_KEY_PREFIX = "app:user:"
NEXT_USER_ID_KEY = "app:user:next_id"


def user_key(user_id: int | str) -> str:
    return f"{USER_KEY_PREFIX}{user_id}"


def get_client() -> redis.Redis:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        print(f"Could not connect to Redis at {REDIS_URL}: {exc}", file=sys.stderr)
        print("Start Redis: docker compose -f docker/docker-compose.yml up -d", file=sys.stderr)
        raise SystemExit(1) from exc
    return client


def user_exists(client: redis.Redis, user_id: str) -> bool:
    return client.exists(user_key(user_id)) == 1


def create_user(client: redis.Redis, name: str, email: str) -> int:
    user_id = int(client.incr(NEXT_USER_ID_KEY))
    key = user_key(user_id)
    client.hset(key, mapping={"name": name, "email": email, "login_count": "0"})
    return user_id


def set_name(client: redis.Redis, user_id: str, name: str) -> None:
    if not user_exists(client, user_id):
        raise SystemExit(f"User {user_id} does not exist.")
    client.hset(user_key(user_id), "name", name)


def set_email(client: redis.Redis, user_id: str, email: str) -> None:
    if not user_exists(client, user_id):
        raise SystemExit(f"User {user_id} does not exist.")
    client.hset(user_key(user_id), "email", email)


def show_user(client: redis.Redis, user_id: str) -> dict[str, str]:
    if not user_exists(client, user_id):
        raise SystemExit(f"User {user_id} does not exist.")
    return client.hgetall(user_key(user_id))


def bump_login(client: redis.Redis, user_id: str) -> int:
    if not user_exists(client, user_id):
        raise SystemExit(f"User {user_id} does not exist.")
    return int(client.hincrby(user_key(user_id), "login_count", 1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Lab 1B: user profile hash")
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create", help="Create user with auto-increment id")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--email", required=True)

    set_name_parser = sub.add_parser("set-name", help="Update name only")
    set_name_parser.add_argument("user_id")
    set_name_parser.add_argument("name")

    set_email_parser = sub.add_parser("set-email", help="Update email only")
    set_email_parser.add_argument("user_id")
    set_email_parser.add_argument("email")

    show_parser = sub.add_parser("show", help="Show all fields for user")
    show_parser.add_argument("user_id")

    bump_parser = sub.add_parser("bump-login", help="Increment login_count by 1")
    bump_parser.add_argument("user_id")

    args = parser.parse_args()
    client = get_client()

    if args.command == "create":
        user_id = create_user(client, args.name, args.email)
        print(f"Created user {user_id}")
        for field, value in show_user(client, str(user_id)).items():
            print(f"  {field}: {value}")
    elif args.command == "set-name":
        set_name(client, args.user_id, args.name)
        print(f"Updated name for user {args.user_id}")
    elif args.command == "set-email":
        set_email(client, args.user_id, args.email)
        print(f"Updated email for user {args.user_id}")
    elif args.command == "show":
        fields = show_user(client, args.user_id)
        print(f"User {args.user_id}:")
        for field, value in fields.items():
            print(f"  {field}: {value}")
    else:
        new_count = bump_login(client, args.user_id)
        print(f"login_count: {new_count}")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
