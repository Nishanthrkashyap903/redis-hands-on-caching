# Module 1 checkpoint

Answers for Labs 1A, 1B, and 1C after completing the data-type labs.

---

## Cross-cutting (all three labs)

### 1. Caching read/write pattern

These labs do **not** use classic caching patterns (cache-aside, read-through, write-through, write-behind) because there is **no separate source of truth** such as a database. The application reads and writes **only Redis**.

For the checkpoint, the accurate description is: Redis is the **system of record** in the lab scope—we are practicing **data structures and atomic commands**, not a cache layer in front of another store.

| Lab | Closest idea (not full cache-aside) |
|-----|-------------------------------------|
| 1A | **Materialized counter** / aggregate stored in Redis (`INCR`) |
| 1B | **Primary profile store** as a Hash (`HSET`, `HINCRBY`) |
| 1C | **Leaderboard as a sorted set** maintained in Redis (`ZINCRBY`, `ZREVRANGE`) |

Real cache-aside appears when we add a DB in later modules (e.g. Module 3).

### 2. If Redis restarts empty mid-day

**In our local setup:** `docker-compose` uses **AOF** (`appendonly yes`) and a **`redis-data` volume**, so a normal **container restart** usually **does not** wipe URL view counts, user profiles, or leaderboard scores.

**If data were truly lost** (empty instance, `docker compose down -v`, or corruption):

| Lab | What users would see |
|-----|----------------------|
| 1A | All view counts **0** / missing (new `INCR` starts from 1 again per URL) |
| 1B | **No users**; `next_id` counter reset → new users may reuse ids unless the app handles it |
| 1C | **Empty leaderboard** until points are added again |

**Nuance:** Persistence is not infinite durability—AOF `fsync` policy and crashes can lose the last seconds of writes. Production “Redis only” still needs backups/replication if the data matters.

### 3. TTL in production?

**For these labs:** We did **not** set TTL. Data lives until we delete it or Redis evicts under `maxmemory` (our compose sets `maxmemory` + `allkeys-lru`).

**Reasoning:** We treated Redis as the **only store** for these entities, so entries should not auto-expire like a cache entry.

**When TTL would still apply elsewhere (even without a DB):** sessions, time-boxed event leaderboards, rate-limit windows, temporary flags. Module 2 goes deeper on TTL and eviction when Redis acts as a **cache** with freshness rules.

---

## Lab 1A — Page views per URL

1. **Pattern:** Not cache-aside; a **counter in Redis** updated on each “hit” (`INCR`), read with `GET`.
2. **Empty Redis:** All URL stats gone; `stats` returns 0 until new hits.
3. **TTL:** Optional in a real product (e.g. roll up to analytics DB and expire daily keys). For a permanent public view counter with no DB, no TTL is reasonable; with `maxmemory`, old/low-traffic keys could be evicted under LRU.

---

## Lab 1B — User profile hash

1. **Pattern:** Not cache-aside; **profile lives in Redis** as a Hash. Partial updates (`HSET` one field, `HINCRBY` on `login_count`) avoid rewriting a whole JSON blob.
2. **Empty Redis:** Profiles and `app:user:next_id` gone; `show` / updates fail until users are recreated.
3. **TTL:** Uncommon if Redis is the authoritative user store. If Redis were a **cache of PostgreSQL**, we would add TTL + invalidation on writes (later modules).

---

## Lab 1C — Leaderboard

1. **Pattern:** Not cache-aside; **ranking state in a sorted set** (`ZINCRBY` to add/subtract points, `ZREVRANGE` for top N). Score floor at 0 enforced in app after `ZINCRBY`.
2. **Empty Redis:** Leaderboard empty; ranks rebuild as points are added.
3. **TTL:** Often **yes** for seasonal/event boards (`EXPIRE` on `app:leaderboard` after the event). For a permanent global ranking with no DB, no TTL matches treating Redis as primary store.

---

## Module 1 complete

- Labs: 1A, 1B, 1C implemented.
- Next: **Module 2** — TTL, expiration, and memory (`REDIS_LEARNING_PATH.md`).
