# Module 3 — Read caching patterns in practice

**Prerequisites:** Modules 0–2 done; Redis running (`docker compose -f docker/docker-compose.yml up -d`); Python venv with `redis` from `requirements.txt`.

**Goal:** Implement **cache-aside** in front of a mock database, measure hits/misses, then tackle **cache stampede** on concurrent misses.

**Key prefix:** `m3:` (e.g. `m3:product:42`) — cleanup with `SCAN m3:*`.

---

## Concepts (you already know the theory — wire it to Redis)

| Step | Cache-aside (lazy loading) |
|------|----------------------------|
| Read | `GET` / `HGETALL` cache key |
| Miss | Load from DB (file or SQLite) |
| Fill | `SET` or `HSET` + **TTL** (`EX` / `EXPIRE`) |
| Hit | Return cached value; **do not** write on read |

**Read-through** (contrast only): the cache layer loads the DB on miss for you — here **your app** owns the miss path.

**Stale-while-revalidate** (preview for later): serve slightly stale data while refreshing in the background — Lab 3B+ / mini project optional stretch.

---

## Mock DB for Lab 3A

Pick one:

1. **JSON file** — e.g. `labs/module-3-cache-aside/data/products.json` as a list or map of products (`id`, `name`, `price`, …).
2. **SQLite** — one `products` table; same fields.

The mock DB is the **source of truth**. Redis is disposable; deleting `m3:*` should not lose product data.

---

## Lab 3A — Product catalog (cache-aside)

**Story:** `GET /products/:id` (CLI or tiny HTTP server) returns one product. First request loads DB; later requests hit Redis until TTL expires.

**Requirements:**

- One product per lookup by numeric or string `id`.
- Cache shape: **Hash per product** (`HSET m3:product:{id} field value …`) — aligns with Module 1B; alternative JSON string in one key is OK if you document why.
- **Always set TTL** on cache entries (Module 2 habit).
- Track **cache hits** and **cache misses** (in-process counters are fine).
- Optional: print **latency** (time one lookup end-to-end).

**Hints:**

- Miss path: `EXISTS` or `HGET` / `HGETALL` → empty → read DB → populate cache → return.
- Hit path: read cache only; no DB call.
- Key: `m3:product:{id}` (or match your `notes/key-conventions.md` if you created it).
- Populate hash: `HSET` multiple fields in one call, then `EXPIRE` (or `EX` on a string key if you use JSON).
- Verify: first call = miss + DB read; second call = hit; after TTL, miss again.

**CLI idea:**

```text
python lab_3a_catalog.py get 101
python lab_3a_catalog.py stats
```

**redis-cli checks:** `TYPE m3:product:101`, `HGETALL m3:product:101`, `TTL m3:product:101`.

**Design question (answer in your notes):** If Redis is empty but DB has the row, what caching strategy are you using on read?

---

## Lab 3B — Cache stampede (after 3A works)

**Story:** Many concurrent requests for the same **missing** key all hit the DB at once.

**Requirements:**

- Simulate concurrency (threads, `asyncio`, or a small shell loop spawning processes).
- Show the problem: N concurrent misses → N DB reads for one `id`.
- Fix with **one** of:
  - **Distributed lock:** `SET m3:lock:product:{id} 1 NX EX <few seconds>` — only the lock holder loads DB and fills cache; others wait/retry or read cache.
  - **Single-flight** in process (one in-flight load per key) — valid for learning; note it does not protect across multiple app instances.

**Hints:**

- Lock must **expire** (`EX`) so a crashed worker does not deadlock forever.
- After acquiring lock, **double-check** cache (another worker may have filled it).
- Release lock with `DEL` in a `finally` block (or let it expire if you keep TTL short).

Do not start 3B until 3A returns correct data on hit and miss.

---

## Mini project 1 — `catalog-cache` (after labs)

Stretch goals from `REDIS_LEARNING_PATH.md`:

- REST or CLI: `GET /products/:id`
- Metrics: hits, misses, latency
- Configurable TTL and stampede-protection toggle

Keep it in `labs/module-3-cache-aside/` or a sibling folder — your choice.

---

## Module checkpoint

Create `notes/module-3-checkpoint.md` with:

1. **Sequence diagram** (ASCII or mermaid): cache **hit**, cache **miss**, **DB down** — what does the app return in each case?
2. Which **read pattern** is Lab 3A? Why is it not read-through?
3. One sentence: what is a **cache stampede** and how does your 3B fix change DB load?

---

## Suggested files (you implement)

```text
labs/module-3-cache-aside/
├── README.md              # this file
├── data/products.json     # or products.db — you create
├── lab_3a_catalog.py      # you write
└── lab_3b_stampede.py     # you write
```

---

## Cleanup

```bash
./scripts/redis-cleanup.sh --prefix m3:
# or SCAN + DEL in redis-cli
```
