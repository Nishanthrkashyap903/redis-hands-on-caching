# Redis Hands-On Learning Path

**Audience:** You already understand caching concepts and read/write strategies (cache-aside, read-through, write-through, write-behind, etc.). This path turns that theory into muscle memory with Redis.

**How to use this path:** Complete modules in order. Each module has **concepts**, **hands-on labs**, and a **mini checkpoint**. Project modules build on prior labs. Keep a local `labs/` folder as you go (we will create it together when you start).

---

## Learning outcomes

By the end you should be able to:

- Run Redis locally (CLI + optional GUI) and reason about persistence, memory, and eviction
- Choose data structures (strings, hashes, lists, sets, sorted sets, streams) for real problems
- Implement cache-aside, TTL, and invalidation patterns safely
- Use Redis for sessions, rate limiting, leaderboards, pub/sub, and simple job queues
- Spot failure modes: stampedes, hot keys, big keys, no TTL, cache/database inconsistency

---

## Prerequisites

- macOS (your environment): Homebrew or Docker
- A language for projects: **Node.js** or **Python** (pick one primary; labs will note both where useful)
- Terminal comfort and basic HTTP/API ideas

---

## Module 0 — Environment setup (Day 1)

| Step | Topic | Hands-on |
|------|--------|----------|
| 0.1 | Install Redis (Homebrew or Docker) | `redis-server`, `redis-cli PING` |
| 0.2 | CLI essentials | `SET`/`GET`, `KEYS` vs `SCAN`, `DBSIZE`, `INFO` |
| 0.3 | Config basics | `redis.conf`: bind, port, `maxmemory`, `maxmemory-policy` |
| 0.4 | Optional tools | Redis Insight or `redis-cli --stat` |
| 0.5 | Client library | Install `redis` (Node) or `redis` (Python) |

**Checkpoint:** Script that connects, sets a key with TTL, reads it back, prints TTL.

**Mini project:** `hello-redis` — single-file client that logs connection, round-trip latency (10 ops), clean shutdown.

---

## Module 1 — Core data types & when to use them (Days 2–3)

| Step | Type | Use case | Key commands |
|------|------|----------|--------------|
| 1.1 | Strings | Counters, simple cache values, JSON blobs | `INCR`, `MSET`, `GETSET`, `SETEX` |
| 1.2 | Hashes | Object-shaped cache (user profile) | `HSET`, `HGET`, `HGETALL`, `HINCRBY` |
| 1.3 | Lists | Recent items, capped logs | `LPUSH`, `LRANGE`, `LTRIM` |
| 1.4 | Sets | Unique tags, dedup | `SADD`, `SISMEMBER`, `SUNION` |
| 1.5 | Sorted sets | Rankings, time-scored feeds | `ZADD`, `ZRANGE`, `ZREVRANK`, `ZINCRBY` |
| 1.6 | Key design | Namespacing `app:entity:id`, avoid huge keys | Convention doc in your repo |

**Labs:**

- Lab 1A: Page view counter per URL (`INCR` + key pattern)
- Lab 1B: User profile hash with partial updates
- Lab 1C: Top-10 leaderboard with sorted set

**Checkpoint:** Explain for each lab which **read/write caching strategy** you are approximating and what happens if Redis disappears.

---

## Module 2 — TTL, expiration, and memory (Day 4)

| Topic | Hands-on |
|--------|----------|
| `EXPIRE`, `TTL`, `PERSIST` | Keys that auto-clean |
| Lazy vs active expiration | Observe with `TTL` polling |
| Eviction policies | `allkeys-lru` vs `volatile-lru` under memory cap |
| Good practices | Always set TTL on cache keys; document exceptions |

**Lab 2:** Fill Redis to `maxmemory` with random keys; observe evictions and hit rate (manual or simple script).

**Checkpoint:** List three production bugs caused by missing or wrong TTL.

---

## Module 3 — Read caching patterns in practice (Days 5–6)

Connect theory to Redis implementation.

| Pattern | Redis implementation sketch |
|---------|------------------------------|
| Cache-aside | App: `GET` cache → miss → DB → `SET` with TTL |
| Read-through | Less common in app-only Redis; compare with library support |
| Stale-while-revalidate | TTL + background refresh flag (lab) |

**Labs:**

- Lab 3A: **Product catalog** — mock DB (JSON file or SQLite), cache-aside with hash per product
- Lab 3B: **Cache stampede** — simulate many concurrent misses; fix with locking (`SET key lock NX EX`) or single-flight

**Mini project 1 — `catalog-cache`**

- REST or CLI: `GET /products/:id`
- Metrics: hits, misses, latency
- Configurable TTL and stampede protection toggle

**Checkpoint:** Draw sequence diagram: cache hit, cache miss, DB down (what does the app return?).

---

## Module 4 — Write patterns & consistency (Days 7–8)

| Pattern | Redis role |
|---------|------------|
| Write-through | Update DB and cache in same request |
| Write-behind | Queue updates; Redis as buffer (intro only) |
| Invalidation vs update | `DEL` vs `HSET` — when to use which |

**Labs:**

- Lab 4A: Update product price — compare **invalidate** vs **update cache**
- Lab 4B: **Write-behind sketch** — `LPUSH` queue + worker flushing to mock DB (no full production queue yet)

**Mini project 2 — `inventory-writes`**

- Stock decrement with optimistic rules in mock DB
- Cache-aside on read; on write choose invalidate or update and document tradeoffs

**Checkpoint:** Name one scenario where write-behind is dangerous without durability guarantees.

---

## Module 5 — Atomicity, transactions, and scripts (Day 9)

| Topic | Commands / APIs |
|--------|------------------|
| Atomic counters / limits | `INCR`, `DECR`, `SET NX` |
| Pipelines | Batch RTT reduction (client) |
| `MULTI` / `EXEC` | Small atomic batches |
| Lua | Complex atomic logic (rate limit + deduct) |

**Lab 5:** Implement **rate limiter**: N requests per minute per IP or API key (`INCR` + `EXPIRE` or sliding window with sorted set).

**Checkpoint:** Why is `MULTI` not a distributed transaction across Redis and PostgreSQL?

---

## Module 6 — Beyond key-value cache (Days 10–12)

| Feature | Mini use case |
|---------|----------------|
| Pub/Sub | Live notifications (no persistence — know the limits) |
| Streams (intro) | Event log tail, consumer groups (conceptual + small lab) |
| HyperLogLog / Bitmap (optional) | Unique visitors, feature flags at scale |

**Mini project 3 — `live-dashboard`**

- Publisher simulates metrics; subscribers print updates
- Optional: persist last N events in a capped list for late joiners

---

## Module 7 — Sessions, auth, and security basics (Day 13)

| Topic | Practice |
|--------|----------|
| Session store | `SET session:{id}` JSON + TTL |
| Rotation / logout | `DEL` session key |
| Secrets | No passwords in Redis; TLS in production note |
| ACLs (awareness) | `ACL LIST` on Redis 6+ |

**Mini project 4 — `session-api`**

- Login → session id in Redis; middleware validates session on protected route

---

## Module 8 — Operations & production awareness (Day 14)

| Topic | What to try locally |
|--------|---------------------|
| Persistence | RDB vs AOF — enable one, restart, check data |
| Replication (concept) | Read replica lag and read-your-writes |
| Sentinel / Cluster (overview) | When single instance breaks |
| Monitoring | `INFO`, `LATENCY DOCTOR`, slowlog |
| Common pitfalls | Hot keys, `KEYS *`, huge values, no connection pooling |

**Lab 8:** Restart Redis with AOF; verify keys survive. Document your local `redis.conf` choices in `notes/local-redis.md`.

---

## Module 9 — Capstone (Days 15–17)

**Capstone: `mini-api-with-redis`**

One small service combining:

1. Cache-aside for reads (Module 3)
2. Write invalidation or update (Module 4)
3. Rate limiting on public endpoints (Module 5)
4. Session or API token store (Module 7)
5. README with architecture diagram and failure modes

Suggested domain: **URL shortener**, **booking slots**, or **social feed (top posts)** — pick one when we start the capstone.

**Deliverables:**

- `README.md` — how to run Redis + app
- `docs/architecture.md` — diagrams + caching strategy per endpoint
- Simple load test notes (even `ab` or `hey` with before/after cache)

---

## Suggested folder layout (create as we progress)

```text
Caching/
├── REDIS_LEARNING_PATH.md          # this file
├── notes/                          # your reflections per module
├── labs/
│   ├── module-0-hello/
│   ├── module-1-data-types/
│   ├── ...
│   └── capstone/
├── docker/
│   └── docker-compose.yml          # optional Redis + app
└── scripts/
    └── redis-cli-snippets.sh
```

---

## Pace options

| Pace | Calendar | Notes |
|------|----------|--------|
| Intensive | ~2 weeks | 1–2 modules per day |
| Steady | ~3–4 weeks | Weekdays only |
| Casual | ~6 weeks | Modules + capstone on weekends |

---

## How we will work together

1. You say **“Start Module 0”** (or the module you are on).
2. We install/configure Redis on your Mac, verify, and build the checkpoint together.
3. Each session: short concept recap → guided commands → small code → checkpoint questions.
4. You keep answers in `notes/module-XX.md` if you want a personal playbook.

---

## Quick reference — mapping your theory to this path

| Your theory | Where it becomes hands-on |
|-------------|---------------------------|
| Cache-aside | Module 3, Projects 1 & 2 |
| Read-through / write-through | Modules 3–4 comparisons |
| Write-behind | Module 4 Lab 4B |
| TTL / freshness | Module 2 |
| Invalidation | Module 4 |
| Stampede / hot key | Module 3 Lab 3B, Module 8 |

---

## Your setup (locked in)

- **Primary language:** Python  
- **Redis:** Docker (`docker/docker-compose.yml`, port `6379`)  
- **Client:** `redis` package (`requirements.txt`)

## Progress

- [x] Module 0 — environment, checkpoint, commands playground
- [x] Module 1 — data types labs; checkpoint `notes/module-1-checkpoint.md`
- [x] Module 2 — TTL & memory; checkpoint `notes/module-2-checkpoint.md`
- [ ] Module 3 — cache-aside (`REDIS_LEARNING_PATH.md` Module 3 section)

## Next step

Say **Start Module 3** to begin cache-aside labs.
