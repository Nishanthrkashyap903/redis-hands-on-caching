# Module 6 — Beyond key-value cache

**Prerequisites:** Modules 0–5 done; Redis running (`docker compose -f docker/docker-compose.yml up -d`); Python venv with `redis` from `requirements.txt`. You understand **cache-aside** and **TTL** — this module is **not** about caching reads; it is about **messaging** and **event-shaped data**.

**Goal:** Use Redis **Pub/Sub** for live fan-out, know its limits vs persistence, skim **Streams** for durable logs, and optionally try **HyperLogLog** / **bitmaps** for cardinality and flags.

**Key prefix:** `m6:` (e.g. `m6:metrics:channel`, `m6:events:stream`, `m6:lab:hll:pageviews`) — cleanup with `SCAN m6:`* or `./scripts/redis-cleanup.sh --prefix m6:` if available.

---

## Concepts (theory → Redis)

| Feature                    | Good for                                                                 | Not good for                                                           | Redis commands                                      |
| -------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------- | --------------------------------------------------- |
| **Pub/Sub**                | Live notifications, dashboard updates, decoupling publishers/subscribers | Durability, replay, “at-least-once” delivery if subscriber was offline | `PUBLISH`, `SUBSCRIBE`, `PSUBSCRIBE`, `UNSUBSCRIBE` |
| **Streams (intro)**        | Append-only event log, consumer groups (later depth)                     | Replacing Kafka at huge scale without ops planning                     | `XADD`, `XREAD`, `XRANGE`, `XLEN`                   |
| **Lists (bridge)**         | Last N events for **late joiners** (mini project option)                 | Unbounded history                                                      | `LPUSH`, `LTRIM`, `LRANGE`                          |
| **HyperLogLog (optional)** | Approx unique visitors / cardinality                                     | Exact counts, small sets                                               | `PFADD`, `PFCOUNT`                                  |
| **Bitmap (optional)**      | Dense feature flags / DAU-style bits                                     | Sparse IDs without key design                                          | `SETBIT`, `GETBIT`, `BITCOUNT`                      |

**Caching tie-in:** Pub/Sub does **not** invalidate your cache. It **signals** “something changed” so apps can refresh or push UI updates. Persistence of messages is **not** Pub/Sub’s job — that is why Streams (or your DB) exist.

---

## Warm-up A — CLI: Pub/Sub (10 min)

Use **two terminals** (or `redis-cli` + Python subscriber later).

**Terminal 1 — subscriber:**

```bash
docker exec -it caching-redis redis-cli
SUBSCRIBE m6:lab:news
```

**Terminal 2 — publisher:**

```bash
docker exec -it caching-redis redis-cli
PUBLISH m6:lab:news "hello"
PUBLISH m6:lab:news '{"metric":"cpu","value":42}'
```

**Observe:** Terminal 1 prints message types (`subscribe`, then `message`). Stop with `Ctrl+C`.

**Questions (answer in** `notes/module-6-checkpoint.md` **later):**

1. If Terminal 1 connects **after** Terminal 2 publishes, does it see past messages?
2. How is that different from `GET` on a cache key you `SET` earlier?

**Optional:** `PSUBSCRIBE m6:lab:`* and publish to `m6:lab:alerts` — pattern subscriptions.

---

## Warm-up B — Python: one publisher, one subscriber (15 min)

**Requirements (your script** `lab_6a_pubsub.py` **or scratch):**

- Connect with `REDIS_URL` (default `redis://localhost:6379/0`).
- **Subscriber** runs in a **background thread** (or second process): subscribes to `m6:metrics:live`, prints payload + timestamp.
- **Publisher** loop: every 1–2 seconds, `PUBLISH` a JSON string (e.g. `{"name":"requests","value": <random>}`) five times, then exit cleanly (unsubscribe / close).
- Main process must not exit before subscriber has printed at least a few messages.

**Hints:**

- redis-py: `pubsub = client.pubsub()` then `pubsub.subscribe("m6:metrics:live")`; listen with `pubsub.get_message()` in a loop (handle `None` / timeout) or `listen()`.
- Subscriber thread needs a **stop flag** or `pubsub.close()` so the process can shut down without hanging.
- Pub/Sub connections are **push mode** — do not mix arbitrary commands on the same connection while subscribed (use a second client for `PUBLISH`).

---

## Lab 6B — Streams intro (small)

**Story:** Treat Redis as a **short event log** for “metric emitted” events (not a full message bus yet).

**Functional requirements:**

- Script `lab_6b_streams.py`:
  - `XADD m6:events:stream * name <metric> value <number>` in a loop (or one `XADD` with field pairs).
  - `XREAD` (or `XRANGE`) to read entries you wrote; print id + fields.
  - Optional: cap length with `MAXLEN ~` on `XADD` so the stream does not grow forever.
- Document in a comment: one scenario where a **Stream** fits better than **Pub/Sub**.

**Hints:**

- Stream IDs are auto (`*`); `XRANGE m6:events:stream - +` reads all.
- Consumer groups (`XGROUP CREATE`, `XREADGROUP`) are Module 6 “stretch” — read Redis docs + one diagram in notes if curious; not required for checkpoint.

---

## Optional Lab 6C — HyperLogLog or bitmap

Pick **one**:

- **HLL:** `PFADD m6:lab:hll:uv user:<id>` for 10k random user ids with duplicates; `PFCOUNT` vs `SCARD` on a set (note memory — do not `SADD` 1M ids on laptop).
- **Bitmap:** `SETBIT m6:lab:flags:day 100 1` and `BITCOUNT` — when would you prefer this over a **Set** of user ids?

---

## Mini project 3 — `live-dashboard` (after warm-ups)

**Story:** A fake metrics source pushes updates; one or more dashboards consume them in real time. Optional: late joiners see the **last N** values from a capped list.

**Requirements:**

| Piece           | Behavior                                                                                              |
| --------------- | ----------------------------------------------------------------------------------------------------- |
| Publisher       | Simulates metrics (timer or loop); `PUBLISH` to `m6:dashboard:metrics`                                |
| Subscriber(s)   | One or more processes/threads; print human-readable lines                                             |
| Optional replay | On subscribe, `LRANGE` a list key `m6:dashboard:history` filled by publisher (`LPUSH` + `LTRIM` to N) |
| Cleanup         | Document keys; delete `m6:*` when done                                                                |

**Design questions (checkpoint):**

- What breaks if you rely on Pub/Sub alone for “every dashboard must see every event forever”?
- Where does **cache-aside** still apply in a system that *also* uses Pub/Sub?

Suggested layout: `labs/module-6-beyond-cache/live_dashboard/` (your package) or single file — your choice.

---

## Module 6 checkpoint (when labs + mini project done)

1. **Pub/Sub vs cache:** Subscriber offline for 5 minutes — what happens to messages published during that window?
2. **Pub/Sub vs Streams:** One sentence each — durability and replay.
3. **Mini project:** Draw ASCII: publisher → Redis → two subscribers; optional list for history.
4. **Production pitfall:** Why Pub/Sub is a poor sole mechanism for **payment processed** notifications?

Write answers in `notes/module-6-checkpoint.md`.

---

## Suggested session order

1. Warm-up A (CLI)
2. Warm-up B (Python pub/sub)
3. Lab 6B (Streams)
4. Mini project `live-dashboard`
5. Optional 6C + checkpoint

When checkpoint is done, tell your instructor **“Module 6 checkpoint done”** and move to **Module 7 — Sessions**.