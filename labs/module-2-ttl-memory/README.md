# Module 2 — TTL, expiration, and memory

**Prerequisites:** Module 1 done; Redis running (`docker compose -f docker/docker-compose.yml up -d`).

**Goal:** Control key lifetime with TTL, see how Redis expires keys, and see what happens when memory is full.

**Key prefix for this module:** `m2:` (easy cleanup with `SCAN m2:`*).

---

## Part A — TTL commands (redis-cli)

Use `./scripts/redis-cli.sh` or one-shot `docker exec -i caching-redis redis-cli ...`.

### A1. Set with TTL upfront

```bash
SET m2:ttl-demo "hello" EX 30
TTL m2:ttl-demo
GET m2:ttl-demo
```

Run `TTL` twice, ~10s apart. What changed?

### A2. TTL on an existing key

```bash
SET m2:ttl-later "no-expiry-yet"
TTL m2:ttl-later
EXPIRE m2:ttl-later 60
TTL m2:ttl-later
```

**Expect:** `-1` means no expiry; after `EXPIRE`, positive seconds.

### A3. Remove expiry

```bash
PERSIST m2:ttl-later
TTL m2:ttl-later
```



### A4. Missing vs expired

After `m2:ttl-demo` expires (wait 30s or use a 5s key):

```bash
GET m2:ttl-demo
TTL m2:ttl-demo
```

**Remember:** `GET` → `(nil)`; `TTL` → `-2` when key is gone.

### A5. Python one-liner (optional)

With venv active, mirror `SET` + `TTL` for `m2:py-ttl` with `ex=15` using your Module 0 client pattern.

---



## Part B — Lazy vs active expiration (observe)

Redis removes expired keys:

- **Lazy:** on access (`GET`, etc.) or when checking TTL
- **Active:** background sampling (`hz` / expire cycle—you may not “see” it in CLI, but huge keyspaces rely on it)

**Exercise:** Create `SET m2:lazy EX 3`, then loop in shell:

```bash
while true; do docker exec -i caching-redis redis-cli TTL m2:lazy; sleep 1; done
```

Note when it flips to `-2`. You do not need to run `GET` for the key to eventually disappear from the keyspace (active expiration can delete idle expired keys).

Write 2–3 sentences in `notes/module-2-checkpoint.md` on what you observed.

---



## Part C — Your compose file today

From `docker/docker-compose.yml`:

- `maxmemory 128mb`
- `maxmemory-policy allkeys-lru`

Meaning when memory is full, Redis can **evict any key** (LRU), not only keys with TTL.

Check live config:

```bash
docker exec -i caching-redis redis-cli CONFIG GET maxmemory
docker exec -i caching-redis redis-cli CONFIG GET maxmemory-policy
docker exec -i caching-redis redis-cli INFO memory | grep -E 'used_memory_human|maxmemory|evicted_keys'
```

---



## Lab 2 — Fill memory and watch evictions

**Story:** Simulate a cache filling up. See `evicted_keys` increase and some keys disappear.

**Requirements (you implement):**

- Script `lab_2_fill_memory.py` (or shell loop) that writes many keys until evictions happen or writes fail.
- Use prefix `m2:fill:` and **large values** (e.g. 50KB–100KB strings) so you hit 128MB without millions of keys.
- Mix optional: **some keys with TTL**, some **without**—note which survive longer under `allkeys-lru` vs what you’d expect under `volatile-lru` (see Part D).
- Print or log: `DBSIZE`, `INFO memory` evicted_keys before/after.

**Hints (not a full solution):**

- `INFO stats` / `INFO memory` → `evicted_keys`
- `MEMORY USAGE m2:fill:1` on a sample key
- Stop when `evicted_keys` increases or growth slows; don’t run forever
- Do **not** use `KEYS` * in production patterns; `DBSIZE` is enough for this lab

**Verify:** You can explain one eviction in your own words: “We added X, memory hit cap, Redis removed Y because policy is …”

---



## Part D — Policy contrast (optional, recommended)

Temporarily understand `volatile-lru` (only evicts keys **with** TTL):

1. Note current `evicted_keys`.
2. Change policy at runtime (lab only):
  `CONFIG SET maxmemory-policy volatile-lru`
3. Fill again with `m2:v:` keys—half with `EX 60`, half with no TTL.
4. Observe which type tends to go first when memory pressure hits.
5. Restore:
  `CONFIG SET maxmemory-policy allkeys-lru`  
   (container restart also resets to compose defaults unless you changed the file)

Do not commit runtime `CONFIG SET` as “production practice”—this is for learning.

---



## Checkpoint — `notes/module-2-checkpoint.md`

1. **Three production bugs** from missing or wrong TTL (your own examples, e.g. stale cache, unbounded growth, privacy/session never expiring).
2. **Lazy vs active** expiration — your observation from Part B.
3. **Lab 2** — short paragraph: what you did, what `evicted_keys` did, how `allkeys-lru` behaved.
4. **Bridge to Module 3:** When Redis is a **cache** in front of a DB, why will we almost always `SET` with TTL?

---



## Suggested layout

```text
labs/module-2-ttl-memory/
  README.md              # this file
  lab_2_fill_memory.py   # you write
notes/
  module-2-checkpoint.md
```

---



## When done

Say **Module 2 done** or ask for hints with what you tried (command output, not “write the script”).

Next in path: **Module 3** — cache-aside with a mock DB.