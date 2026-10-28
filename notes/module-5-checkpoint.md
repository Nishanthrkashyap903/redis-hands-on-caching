# Module 5 checkpoint — atomicity, transactions, rate limiting

**Labs:** `labs/module-5-atomicity/` — `warmup_pipeline.py`, `lab_5_rate_limit.py` (fixed window), `lab_5_sliding_window.py` (ZSET sliding).

**Key prefixes:**

| Prefix | Use |
|--------|-----|
| `m5:rl:{hash}` | Fixed-window counter (`lab_5_rate_limit.py`) |
| `m5:rl:slide:{hash}` | Sliding-window ZSET (`lab_5_sliding_window.py`) |
| `m5:lab:*` | Warm-ups (pipeline / MULTI) |

Hash = first 16 hex chars of SHA-256 of API key string.

---

## 1. Why `MULTI` / `EXEC` is not a distributed transaction (Redis + PostgreSQL)

**Two systems, two commit points.** `MULTI` / `EXEC` applies only to commands **queued on that Redis connection**. PostgreSQL commits in a separate transaction on the database. Redis does not participate in Postgres `BEGIN` / `ROLLBACK`, and Postgres does not undo Redis after `EXEC`.

**Example failure:** App runs `EXEC` on Redis (quota incremented), then crashes before `db.commit()`. Redis state persists; DB never committed — or the opposite order leaves cache and DB inconsistent. Only the **application** can reconcile (compensating commands, outbox, idempotency keys).

**`MULTI` / `EXEC` on Redis alone:**

| Phase | Effect |
|-------|--------|
| After `MULTI`, before `EXEC` | Commands are **queued only** — **not applied**. `DISCARD` or disconnect → **no** changes from that transaction. |
| After successful `EXEC` | Queued commands **are applied**. **No automatic rollback** if later app logic fails or if a command in the batch errors after earlier ones succeeded. |

**Not the same as SQL:** Postgres can `ROLLBACK` the whole transaction. Redis `MULTI` / `EXEC` does not undo successful steps inside `EXEC` when something else “shouldn’t have happened.”

---

## 2. Fixed window vs sliding window

### Fixed window (Lab 5 — `INCR` + TTL / Approach A–B, optional Lua)

**Mechanism:** One counter per key; window boundary via `EXPIRE` on first hit (A) or `SET 0 NX EX` on miss (B).

**Good enough:** Internal APIs, coarse “~N per minute” limits, low QPS, cost-sensitive (one key, few commands).

**Fails / risks:**

| Risk | Detail |
|------|--------|
| **Boundary burst** | Up to ~**2N** requests in a short span across adjacent windows (N at end of bucket + N after reset). |
| **Missing TTL (Approach A)** | `INCR` then crash or bug before `EXPIRE` → key with **no TTL** (`TTL == -1`) → counter never resets → effective permanent block or wrong limit. Approach B sets `EX` at window open on `-2` to reduce that on the happy path. |
| **Deny still `INCR`s** | Simple design increments then denies; Redis count can exceed N until expiry. |

**Implemented modes:** `a`, `b`, `a-lua`, `b-lua` in `lab_5_rate_limit.py`.

### Sliding window (Lab 5 extension — ZSET + Redis `TIME`)

**Mechanism:** Scores = event time (ms from `TIME`); `ZREMRANGEBYSCORE` prunes; `ZCARD` vs N; `ZADD` only if allowed. **Lua** runs prune + count + conditional `ZADD` atomically (`--mode lua`).

**Good enough:** Stricter “N in the last W seconds,” abuse-sensitive public APIs, avoiding fixed-window seam burst **while state exists**.

**Fails / costs:**

| Risk | Detail |
|------|--------|
| **Not “zero burst” ever** | No classic **2N fixed seam** with continuous traffic and a live ZSET. After **idle key `EXPIRE`**, key is deleted → next caller gets **up to N fresh allows** (post-idle burst, not seam burst). |
| **Operational cost** | Must prune old scores every request; more memory and CPU than one counter. |
| **Python multi-command path (`--mode py`)** | `ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` across trips → **race**; use **Lua** under concurrency. |
| **Time** | Use **Redis `TIME`** in Lua (as in lab); app clock skew breaks multi-app correctness if mixed. |

**Key TTL:** `EXPIRE` on the ZSET on each allow refreshes **idle cleanup**; limit math is **score pruning**, not key TTL.

---

## 3. Pipeline vs `MULTI` / `EXEC` (and concurrency)

**Redis executes one command at a time** on a single instance. Many clients send concurrently; commands are **serialized**, not parallel on the server.

### Pipeline **without** `MULTI`

- **Purpose:** Batch commands → **fewer round trips**.
- **Within one flushed pipeline** from one client, Redis typically runs those commands **back-to-back** without other clients interleaving **between those specific commands**.
- **Does not fix:** Check-then-act in the **app** across **two** `execute()` calls or two network trips (e.g. `ZCARD` in Python, then `ZADD`). **Another client can run between those trips** → race.

### With `MULTI` / `EXEC` (or `pipeline(transaction=True)`)

- Queued commands run as one block: **no other client** interleaves **inside** that `EXEC`.
- **Does not fix:** **Conditional** logic (`EXPIRE` only if `n == 1`; `ZADD` only if under limit). Plain `MULTI` cannot branch on the result of an earlier queued command without **Lua**.
- **Does not fix:** Redis + DB atomicity (see §1).

### Rate limiting takeaway

| Tool | Role |
|------|------|
| `INCR` / `SET NX` | Single-step atomic ops |
| Pipeline | RTT |
| `MULTI` / `EXEC` | Fixed multi-command block, no interleaving |
| **Lua (`EVAL`)** | Conditional multi-step (fixed A/B, sliding ZSET) in **one** atomic script |

**Warm-up:** `warmup_pipeline.py` — pipeline batch vs `pipe.multi()` + `INCR` ×2.

---

## 4. Lua (brief)

- Whole script runs **atomically vs other clients**; **no rollback** if a later `redis.call` errors after earlier ones succeeded.
- **`TIME` in script** for sliding window scores and prune cutoff (see `lab_5_sliding_window.py`, `redis-lua-scripts.md`).

---

## 5. References in repo

- `labs/module-5-atomicity/rate-limit-approaches-and-failures.md`
- `labs/module-5-atomicity/redis-lua-scripts.md`
- Module 5 README checkpoint questions (aligned with §1–§3 above)
