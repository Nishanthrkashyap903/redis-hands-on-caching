# Module 4 — Write patterns & consistency

**Prerequisites:** Modules 0–3 done; Redis running (`docker compose -f docker/docker-compose.yml up -d`); Python venv with `redis` from `requirements.txt`. Comfortable with Lab 3A read path (cache-aside, hash per product, TTL).

**Goal:** On **writes**, keep the mock DB authoritative while deciding what to do in Redis — **invalidate** vs **update cache**, then sketch **write-behind** with a list queue.

**Key prefix:** `m4:` (e.g. `m4:product:101`, `m4:write-queue`) — cleanup with `SCAN m4:`* or `./scripts/redis-cleanup.sh --prefix m4:`.

**Mock DB:** Reuse `labs/module-3-cache-aside/data/products.json` (same products). Writes update that file (or a copy in this folder if you prefer isolation — document which file is truth).

---



## Concepts (theory → Redis)


| Pattern                    | Who updates what on write                             | Redis in this module                                                |
| -------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------- |
| **Cache-aside (read)**     | App wrote cache only on **miss** (Module 3)           | Unchanged read path                                                 |
| **Write-through**          | App updates **DB and cache in one request**           | `HSET` (or `DEL` then next read refills) + DB write in same handler |
| **Write-behind**           | App writes **cache/queue first**; DB catches up async | Lab 4B: `LPUSH` job, worker `RPOP` / `BLPOP` → flush to JSON        |
| **Invalidation vs update** | After DB success: drop cache entry or patch fields    | `DEL m4:product:{id}` vs `HSET` price fields + keep/refresh TTL     |


**Invalidation (lazy):** Simpler mental model — cache always refilled on next read (your 3A miss path). Risk: brief window where cache is empty and many readers miss together (you know how to mitigate from 3B).

**Update cache (write-through slice):** Next read is a hit with fresh data; you must update **every** field you cache and handle partial failures (DB ok, Redis fail — what do you return?).

---



## Lab 4A — Update product price (invalidate vs update)

**Story:** Admin updates `price_cents` for product `101`. Implement **two modes** (CLI flag or subcommand) that both:

1. Persist the new price to the JSON file (source of truth).
2. Apply a different Redis strategy:
  - `invalidate`**:** `DEL m4:product:{id}` (and delete `m4:nf:product:{id}` if you use negative cache).
  - `update`**:** `HSET m4:product:{id} price_cents <new>` (and any other fields you keep in the hash); refresh TTL with `EXPIRE`.

**Requirements:**

- Reuse or mirror the **read** path from 3A (`get <id>`) but with `m4:` keys — or one script with shared helpers; your choice.
- After a successful write, demonstrate behavior:
  - **invalidate:** `get 101` → miss → loads new price from JSON.
  - **update:** `get 101` → hit → new price **without** reading JSON (prove with a log line: `source: cache`).
- Optional: if product was **not** in cache before write, document what each mode does (nothing vs create hash).

**Hints:**

- Write order: many teams do **DB first, then cache** so a failed cache does not lie about committed data.
- If you only `HSET` price but other hash fields are stale, you have a **partial update** bug — either write all cached fields or invalidate.
- `redis-cli`: after `update`, `HGET m4:product:101 price_cents`; after `invalidate`, `EXISTS m4:product:101` → 0.

**CLI idea:**

```text
python lab_4a_price_write.py get 101
python lab_4a_price_write.py set-price 101 2999 --mode invalidate
python lab_4a_price_write.py set-price 101 3199 --mode update
```

**Design question (notes):** When is **invalidate** safer than **update** for a product hash with five fields?

---



## Lab 4B — Write-behind sketch (queue + worker)

**Story:** “Fast” path accepts a price change, enqueues work, returns quickly; a **worker** drains the queue and writes JSON.

**Requirements:**

- Enqueue: `LPUSH m4:write-queue <json job>` (job: at least `product_id`, `price_cents`, maybe `enqueued_at`).
- Worker loop (separate process or subcommand `worker`): **`LPUSH` + `BRPOP`** (FIFO) with timeout, apply update to JSON file, then invalidate cache (see `lab_4b_write_behind.py`).
- **No** production-grade retry/idempotency required — but note in comments what breaks if the worker crashes mid-queue.
- Compare latency feel: enqueue-only vs Lab 4A synchronous write.

**Hints:**

- This is **not** full write-behind to Redis as source of truth — the queue is in Redis, truth stays JSON (intro level per path).
- If read path still uses cache-aside, stale reads are possible until worker runs — name that failure mode.
- Cap queue inspection: `LRANGE m4:write-queue 0 -1` (list key name is your choice; stay consistent).

Do not start 4B until 4A `set-price` works for both modes.

---



## Mini project 2 — `inventory-writes` (after labs)

From `REDIS_LEARNING_PATH.md`:

- Stock decrement with optimistic rules in mock DB (`in_stock` / quantity if you add it).
- Cache-aside on read; on write choose invalidate or update and **document tradeoffs** in `notes/module-4-checkpoint.md` or a short `DESIGN.md` in the lab folder.

---



## Module checkpoint

Create `notes/module-4-checkpoint.md` with:

1. **Two sequence diagrams** (mermaid or ASCII): write with **invalidate** vs **update** after DB commit.
2. One paragraph: **write-through** vs **write-behind** — which lab matches which?
3. **Checkpoint question (path):** Name one scenario where write-behind is dangerous without durability guarantees.

---



## Suggested files (you implement)

```text
labs/module-4-write-patterns/
├── README.md                 # this file
├── lab_4a_price_write.py     # you write
└── lab_4b_write_behind.py    # you write (queue + worker)
```

---



## Cleanup

```bash
./scripts/redis-cleanup.sh --prefix m4:
```

