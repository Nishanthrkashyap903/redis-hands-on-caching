# Module 5 — Atomicity, transactions, and scripts

**Prerequisites:** Modules 0–4 done; Redis running (`docker compose -f docker/docker-compose.yml up -d`); Python venv with `redis` from `requirements.txt`. You already used `SET … NX EX` in Module 3B (stampede lock) — same building block for limits and leases.

**Goal:** Reason about **one Redis command = atomic**, when **check-then-set in the app is unsafe**, and when you need `MULTI`**/**`EXEC`, **pipelines**, or **Lua**. Build a **rate limiter** (Lab 5).

**Key prefix:** `m5:` (e.g. `m5:rl:apikey:abc123`, `m5:lab:counter`) — cleanup with `SCAN m5:`* or `./scripts/redis-cleanup.sh --prefix m5:`.

---



## Concepts (theory → Redis)


| Idea                 | What Redis gives you                                                  | Pitfall                                                                         |
| -------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| **Atomic increment** | `INCR` / `INCRBY` — no lost updates vs `GET` + `SET`                  | Counter without window/TTL → unbounded key lifetime                             |
| **Conditional set**  | `SET key value NX` or `SET key value NX EX ttl`                       | Two round trips (`EXISTS` then `SET`) race under concurrency                    |
| **Pipeline**         | Client batches commands; **one** network round trip                   | **Not** atomic unless you also use `MULTI`/`EXEC` or a single command           |
| `MULTI` **/** `EXEC` | Queue commands; Redis runs the batch **atomically** (no interleaving) | Not rollback on “business logic failure”; errors after `EXEC` need app handling |
| **Lua (**`EVAL`**)** | Multiple steps as **one** atomic script on the server                 | Keep scripts short; know key count for cluster (later)                          |


**Bridge from Module 3:** Stampede lock = `SET lock NX EX`. Rate limit = often `INCR` + window TTL, or a sorted set for sliding windows.

---



## Warm-up A — CLI: atomic vs racy (5 min)

In `redis-cli` (or `docker exec -i caching-redis redis-cli`):

1. `SET m5:lab:counter 0` then `INCR m5:lab:counter` three times — note each reply is the **new** value.
2. `DEL m5:lab:once` then `SET m5:lab:once 1 NX` twice — what does the second reply mean?
3. Optional: `SET m5:lab:lease holder1 NX EX 10` then `TTL m5:lab:lease` — ties to 3B lock TTL.

**Question:** Why is `INCR` safe for concurrent clients but `GET` + `SET` is not?

---



## Warm-up B — Pipeline vs transaction (Python sketch)

**Requirements (your script** `warmup_pipeline.py` **or a scratch cell):**

- Use `client.pipeline()` to send **10** `INCR m5:lab:pipe` in one round trip; print the **last** returned value.
- In a **second** experiment, use `pipe.multi()` then `INCR` twice on `m5:lab:multi`, then `EXEC` — confirm both increments applied (no other client can interleave between `MULTI` and `EXEC`).

**Hints:**

- `pipeline()` alone = batching for RTT; `pipeline(transaction=True)` / `multi()` = `MULTI`/`EXEC` semantics in redis-py.
- After warm-up, `DEL m5:lab:pipe m5:lab:multi`.

---



## Lab 5 — Rate limiter (N requests per minute)

**Story:** Protect a fake API endpoint. Each request supplies an **API key** (or IP string). Allow at most **N** successful checks per **fixed 60-second window** per key.

**Functional requirements:**

- CLI or function: `allow(api_key: str) -> bool` — `True` if under limit, `False` if limited.
- Configurable **N** (e.g. `--limit 5`) and window **60s** (constant in code is fine for v1).
- Log or print: `allowed` / `denied` and optional remaining quota for debugging.
- Use prefix `m5:rl:{api_key}` (sanitize key if needed — no spaces; consider hashing untrusted strings in notes).

**Two acceptable designs (pick one for v1, document the other in notes):**


| Approach                        | Sketch                                                                      | Tradeoff                            |
| ------------------------------- | --------------------------------------------------------------------------- | ----------------------------------- |
| **Fixed window counter**        | First request in window: `INCR` + `EXPIRE` on first hit; compare count to N | Simple; burst at window boundaries  |
| **Sliding window (sorted set)** | `ZADD` with score = timestamp ms; `ZREMRANGEBYSCORE` old; `ZCARD` vs N      | Smoother; more commands (Lua helps) |


**Concurrency:** Your limit check must be safe when many threads/processes hit the same API key at once. Name which operations are atomic without extra locking.

**Design reference:** [rate-limit-approaches-and-failures.md](rate-limit-approaches-and-failures.md) — fixed-window variants (A/B/C), sliding sketch, anti-patterns, and failure modes. [redis-lua-scripts.md](redis-lua-scripts.md) — how `EVAL`/`EVALSHA` runs, pros/cons.

**Tests you should run manually:**

- Send N+1 requests with the same key in one process — last should deny.
- Two terminals / threads hammering one key — count should not exceed N by “much” (fixed window may allow edge bursts; explain in notes).

**CLI idea:**

```text
python lab_5_rate_limit.py --key demo --limit 5
python lab_5_rate_limit.py --key demo --limit 5 --mode a --count 7
python lab_5_rate_limit.py --key demo --limit 5 --mode a-lua --burst 10
python lab_5_rate_limit.py --key demo --limit 5 --burst 10   # optional: simulate concurrent hits
```

`--mode`: `a` / `b` (Python), `a-lua` / `b-lua` (atomic Lua). Default `b`.

**Do not** build HTTP yet — CLI is enough. Module 9 capstone will wire rate limiting to an API.

**Sliding window (extension):** [`lab_5_sliding_window.py`](lab_5_sliding_window.py) — ZSET + Redis `TIME`; `--mode py` (multi-command) vs `--mode lua` (atomic). Key prefix `m5:rl:slide:`.

---



## Optional stretch (no lab credit required)

- Implement **same** limit with a tiny **Lua** script (`EVAL`) so INCR + EXPIRE + compare is one atomic unit on fixed-window v1.
- Compare RTT: 3 separate commands vs pipeline vs Lua (rough `time.perf_counter` loop).

---



## Module checkpoint

Answer in `notes/module-5-checkpoint.md`:

1. **Why is** `MULTI`**/**`EXEC` **not a distributed transaction across Redis and PostgreSQL?** (What commits where, and what happens if the app crashes between them?)
2. For your Lab 5 design: **fixed window vs sliding** — one production scenario where each is “good enough” and one where it fails.
3. **Pipeline without** `MULTI`**:** Can two clients’ increments interleave? **With** `MULTI`**/**`EXEC`**?**

---



## Files to add (you implement)


| File                           | Purpose            |
| ------------------------------ | ------------------ |
| `lab_5_rate_limit.py`          | Lab 5 fixed-window rate limiter |
| `lab_5_sliding_window.py`    | Sliding-window ZSET (`--mode py` / `lua`) |
| `warmup_pipeline.py`           | Optional warm-up B |
| `notes/module-5-checkpoint.md` | Checkpoint answers |


---



## References in this repo

- `labs/module-0-hello/redis-commands-playground.md` — `INCR`, `SET NX`
- `labs/module-3-cache-aside/lab_3b_stampede.py` — `SET NX EX` pattern
- `labs/module-2-ttl-memory/lab_2_fill_memory.py` — `client.pipeline()` example

