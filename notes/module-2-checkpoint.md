# Module 2 checkpoint

## 1. Three production bugs from missing or wrong TTL

1. **TTL too long:** Cached social posts (or feeds) stay served after the source has newer content → **stale reads** for users.
2. **No TTL:** Cache keys accumulate without bound → **memory growth** and operational cost; looks like a leak when nothing ever expires.
3. **TTL too short** on data that rarely changes: Frequent expiry → **cache misses** and repeated DB load (**overload** on the database) without much benefit.

## 2. Lazy vs active expiration

**Lazy expiration:** An expired key is removed when something **accesses** it (or checks it), e.g. `GET`, `HGET`, `TTL`. Expired keys nobody touches can **linger in memory** until active expiration or access catches them.

**Active expiration:** Redis **periodically samples** keys with TTL in the background and deletes those past their deadline—not a full scan of every key every second, but enough to stop huge piles of idle expired keys. There is CPU cost, which is why both lazy and active exist together.

## 3. Lab 2 — fill memory / evictions

- **`allkeys-lru`:** Under memory pressure, Redis can evict **any** key, whether it has TTL or not (LRU-style approximation).
- **`volatile-lru`:** Eviction candidates are keys **with TTL set**; keys without TTL are not chosen for eviction on that policy (they can still cause memory pressure).

Observed via `lab_2_fill_memory.py` and `INFO memory` / `evicted_keys` before and after fill.

## 4. Bridge to Module 3

When Redis sits **in front of a DB**, the DB is the **source of truth**. Cache entries get a **TTL** so responses stay fast on hits, but data is allowed to age out and be refreshed from the DB—balancing freshness, memory, and load.

---

Module 2 complete → **Module 3** (cache-aside with mock DB).
