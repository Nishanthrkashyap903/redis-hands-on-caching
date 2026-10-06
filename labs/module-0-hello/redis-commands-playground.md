# Redis commands playground (hands-on)

Run these in order with your container up:

```bash
cd "/Users/nishanthrkashyap/Desktop/System Design/Caching"
docker compose -f docker/docker-compose.yml up -d
```

**Two ways to run commands:**

| Mode | How |
|------|-----|
| Interactive | `docker exec -it caching-redis redis-cli` then type commands |
| One-shot | `docker exec -i caching-redis redis-cli COMMAND args...` |

Tip: In interactive mode, use the **Up arrow** to repeat commands. `HELP @string` shows string command help.

Use a **lab prefix** so you do not clash with your Python scripts: keys like `lab:user:1`.

---

## 0. Sanity check

```bash
docker exec -i caching-redis redis-cli PING
```

**Expect:** `PONG` — server is alive.

```bash
docker exec -i caching-redis redis-cli INFO server | head -n 8
```

**Expect:** lines like `redis_version`, `os` — metadata about the instance (not your data).

---

## 1. Strings — the default type

Redis values are often strings; many patterns (JSON blobs, counters) use strings.

```bash
docker exec -i caching-redis redis-cli SET lab:greeting "hello"
docker exec -i caching-redis redis-cli GET lab:greeting
```

**What happened:** `SET` stored a key→value mapping in memory. `GET` read it back.

```bash
docker exec -i caching-redis redis-cli SET lab:temp "expires-soon" EX 30
docker exec -i caching-redis redis-cli TTL lab:temp
docker exec -i caching-redis redis-cli GET lab:temp
```

**What happened:** `EX 30` sets **TTL** (time to live) in seconds. `TTL` shows seconds remaining (`-1` = no expiry, `-2` = key missing).

```bash
docker exec -i caching-redis redis-cli SET lab:counter "0"
docker exec -i caching-redis redis-cli INCR lab:counter
docker exec -i caching-redis redis-cli INCR lab:counter
docker exec -i caching-redis redis-cli GET lab:counter
```

**What happened:** `INCR` is **atomic** — safe for concurrent counters (one Redis command = one atomic step).

```bash
docker exec -i caching-redis redis-cli MSET lab:a "alpha" lab:b "beta"
docker exec -i caching-redis redis-cli MGET lab:a lab:b lab:missing
```

**Expect:** `MGET` returns values; missing key shows as `(nil)`.

**Try yourself:** `SET lab:only-once "x" NX` twice. What does the second command return? (Hint: `NX` = only if **not** exists.)

---

## 2. Key metadata and cleanup

```bash
docker exec -i caching-redis redis-cli EXISTS lab:greeting
docker exec -i caching-redis redis-cli TYPE lab:greeting
docker exec -i caching-redis redis-cli TYPE lab:counter
```

**Expect:** `EXISTS` → `1` or `0`. `TYPE` → `string` for those keys.

```bash
docker exec -i caching-redis redis-cli EXPIRE lab:greeting 300
docker exec -i caching-redis redis-cli TTL lab:greeting
```

**What happened:** You added TTL to an existing key without rewriting the value.

```bash
docker exec -i caching-redis redis-cli DEL lab:a lab:b
docker exec -i caching-redis redis-cli EXISTS lab:a
```

**Expect:** `DEL` returns count of keys removed; `EXISTS` → `0`.

**Caching link:** **Invalidation** often means `DEL` (or letting TTL expire).

---

## 3. Finding keys — avoid `KEYS *` in production

```bash
docker exec -i caching-redis redis-cli SCAN 0 MATCH lab:* COUNT 100
```

**What happened:** `SCAN` walks the keyspace in **chunks** (cursor `0` starts). Safer than `KEYS lab:*` on large databases.

Run `SCAN` again with the **cursor** number returned in the first line until cursor is `0` again.

**Rule of thumb:** Learn with `KEYS lab:*` on your laptop; in production prefer `SCAN`.

---

## 4. Hashes — one key, many fields (object-shaped data)

```bash
docker exec -i caching-redis redis-cli HSET lab:user:1 name "Ada" role "engineer" score "10"
docker exec -i caching-redis redis-cli HGET lab:user:1 name
docker exec -i caching-redis redis-cli HGETALL lab:user:1
```

**What happened:** One Redis **key** (`lab:user:1`), multiple **fields** inside. Good for profiles without one giant JSON string (you can still store JSON in a string if you prefer).

```bash
docker exec -i caching-redis redis-cli HINCRBY lab:user:1 score 5
docker exec -i caching-redis redis-cli HGET lab:user:1 score
```

**Try yourself:** `HDEL lab:user:1 role` then `HGETALL`. Compare memory/updates vs storing the whole user as one `SET` string.

---

## 5. Lists — ordered sequence (queues, recent items)

```bash
docker exec -i caching-redis redis-cli DEL lab:recent
docker exec -i caching-redis redis-cli LPUSH lab:recent "c" "b" "a"
docker exec -i caching-redis redis-cli LRANGE lab:recent 0 -1
```

**Expect:** order `a`, `b`, `c` — `LPUSH` adds to the **left** (head).

```bash
docker exec -i caching-redis redis-cli RPUSH lab:recent "d"
docker exec -i caching-redis redis-cli LRANGE lab:recent 0 -1
```

```bash
docker exec -i caching-redis redis-cli LPOP lab:recent
docker exec -i caching-redis redis-cli LRANGE lab:recent 0 -1
```

**What happened:** List as a double-ended queue. `LTRIM` (look up `HELP LTRIM`) caps length — useful for “last N events.”

---

## 6. Sets — unique unordered members

```bash
docker exec -i caching-redis redis-cli DEL lab:tags
docker exec -i caching-redis redis-cli SADD lab:tags redis caching docker
docker exec -i caching-redis redis-cli SADD lab:tags redis
docker exec -i caching-redis redis-cli SMEMBERS lab:tags
```

**Expect:** `redis` only once.

```bash
docker exec -i caching-redis redis-cli SISMEMBER lab:tags caching
docker exec -i caching-redis redis-cli SISMEMBER lab:tags kafka
```

**Use case:** tags, “have we seen this id?”, deduplication.

---

## 7. Sorted sets — unique members with a score (rankings)

```bash
docker exec -i caching-redis redis-cli DEL lab:leaderboard
docker exec -i caching-redis redis-cli ZADD lab:leaderboard 100 player_a 250 player_b 250 player_c
docker exec -i caching-redis redis-cli ZREVRANGE lab:leaderboard 0 2 WITHSCORES
```

**What happened:** Members sorted by **score**. `ZREVRANGE` = highest scores first.

```bash
docker exec -i caching-redis redis-cli ZINCRBY lab:leaderboard 50 player_a
docker exec -i caching-redis redis-cli ZREVRANK lab:leaderboard player_a
```

**Try yourself:** Add two players with the same score; check order with `ZREVRANGE ... WITHSCORES`.

---

## 8. Server introspection (after your labs)

```bash
docker exec -i caching-redis redis-cli DBSIZE
docker exec -i caching-redis redis-cli MEMORY USAGE lab:user:1
```

`DBSIZE` ≈ number of keys (all types). `MEMORY USAGE` needs Redis 4+ (you have 7).

```bash
docker exec -i caching-redis redis-cli --stat
```

Press `Ctrl+C` to stop — live throughput snapshot.

---

## 9. Connect Python to what you typed

With venv active:

```bash
python -c "
import redis
r = redis.from_url('redis://localhost:6379/0', decode_responses=True)
print('greeting:', r.get('lab:greeting'))
print('user:', r.hgetall('lab:user:1'))
print('leader top:', r.zrevrange('lab:leaderboard', 0, 0, withscores=True))
"
```

**Point:** CLI and Python share the **same keyspace** on DB `0`.

---

## 10. Clean up lab keys (optional)

```bash
docker exec -i caching-redis redis-cli DEL lab:greeting lab:temp lab:counter lab:user:1 lab:recent lab:tags lab:leaderboard lab:only-once
```

Or delete by pattern (fine locally):

```bash
docker exec -i caching-redis redis-cli --scan --pattern 'lab:*' | xargs -r docker exec -i caching-redis redis-cli DEL
```

(macOS `xargs` may not have `-r`; if it fails, delete keys from `SCAN` output manually.)

---

## Command cheat sheet (by job)

| Job | Commands |
|-----|----------|
| Read/write string | `GET`, `SET`, `SETEX`, `MGET`, `MSET` |
| Counter | `INCR`, `INCRBY`, `DECR` |
| Object fields | `HSET`, `HGET`, `HGETALL`, `HINCRBY` |
| Queue / recent list | `LPUSH`, `RPUSH`, `LPOP`, `LRANGE`, `LTRIM` |
| Unique items | `SADD`, `SISMEMBER`, `SMEMBERS` |
| Ranking | `ZADD`, `ZINCRBY`, `ZRANGE`, `ZREVRANGE`, `ZRANK` |
| Expiry | `EXPIRE`, `TTL`, `PERSIST` |
| Introspection | `TYPE`, `EXISTS`, `DBSIZE`, `INFO`, `SCAN` |

Official reference: [redis.io commands](https://redis.io/commands/)

---

## Reflection prompts (write 1–2 sentences each in `notes/`)

1. When would you use a **Hash** vs one **string** containing JSON?
2. Why is `INCR` better than read-modify-write with `GET` + `SET` under concurrency?
3. What does TTL ` -2` mean when you `GET` the same key?

When this feels natural, say **Start Module 1** — we will use hints for the labs, not full solutions.
