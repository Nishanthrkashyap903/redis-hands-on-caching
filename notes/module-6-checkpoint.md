# Module 6 checkpoint — Pub/Sub, streams, live dashboard

**Labs:** `labs/module-6-beyond-cache/` — `lab_6a_pubsub.py`, `lab_6b_streams.py`. Notes: `pubsub-publisher-subscriber.md`.

**Key prefixes:**

| Prefix | Use |
|--------|-----|
| `m6:metrics:live` | Pub/Sub warm-up B |
| `m6:events:stream` | Streams lab 6B |
| `m6:dashboard:*` | Mini project 3 (metrics channel, optional history list / stream) |

---

## Mini project — design questions

### What breaks if you rely on Pub/Sub alone for “every dashboard must see every event forever”?

**Pub/Sub does not store messages.** It only pushes to connections that are **subscribed at publish time**. Anything published while a dashboard is offline, restarting, or on a broken connection is **lost** for that consumer—there is no backlog on the channel.

**“Forever” is impossible with Pub/Sub alone.** Even hybrid patterns (list or stream with `MAXLEN`) keep a **bounded** window (last N), not a complete archive of every event ever.

**Fan-out vs durability:** Pub/Sub **does** deliver to every **online** subscriber on the channel. What breaks is **durability, replay, and guarantees**—not one-to-many live delivery.

**Mitigations:** optional **capped list** (`LPUSH` + `LTRIM` + `LRANGE` on join) or **streams** (`XREVRANGE` catch-up + `XREAD` tail); both still need an explicit retention policy. For strict “must not lose payment-like events,” use **DB**, **outbox**, or a **queue/stream** with acks—not Pub/Sub alone.

### Where does cache-aside still apply in a system that *also* uses Pub/Sub?

**Pub/Sub is for signals and live fan-out, not for the main read path of entity state.**

| Concern | Pattern |
|---------|---------|
| Serving product, profile, session-shaped reads | **Cache-aside:** `GET` / `HGET` → miss → DB → `SET` / `HSET` with TTL |
| Live metric ticks on a dashboard | **Pub/Sub** or **streams** (events, not cache-aside) |
| After a write: other app instances still show stale cache | **Pub/Sub invalidation:** `PUBLISH cache:invalidate` → subscribers `DEL` keys or evict local cache → **next request** still uses cache-aside |

**Flow:** Admin updates product 42 → DB commit → `DEL product:42` on writer → `PUBLISH` invalidation → other servers `DEL` → user `GET` → miss → DB → `SET` with TTL. The **new price** comes from cache-aside/DB, not from the pub/sub payload as source of truth.

**Anti-pattern:** Using only Pub/Sub bodies as the only copy of critical state—no TTL key, no DB on miss, no replay when offline.

---

## 1. Pub/Sub vs cache — subscriber offline 5 minutes

During those 5 minutes the publisher may `PUBLISH` many messages. **Redis does not queue them** for that subscriber. When the subscriber reconnects and `SUBSCRIBE`s again, it receives **only publishes that happen after** it is subscribed—**nothing** from the offline window.

A **cache key** (`SET` / hash with TTL) is different: after reconnect, `GET` still returns the **last written value** (until TTL or eviction). Pub/Sub answers “what happened **live**”; cache answers “what is **stored** now.”

Optional list/stream replay restores **last N** stored events on join, not Pub/Sub’s missed live pushes.

---

## 2. Pub/Sub vs Streams — one sentence each

**Pub/Sub — durability:** Messages are **not persisted** for delivery; if no subscriber is listening, the message is not retained on the channel for later replay.

**Pub/Sub — replay:** **No replay**; late subscribers only see traffic after they subscribe.

**Streams — durability:** Entries are **stored** in the stream key (subject to `MAXLEN` / `DEL` / eviction) until trimmed or deleted.

**Streams — replay:** Consumers can **read history** (`XRANGE` / `XREVRANGE`) and tail new entries (`XREAD` from `last_id`); replay is **bounded** by retention (`MAXLEN ~`, etc.).

---

## 3. Mini project — ASCII (publisher → Redis → subscribers)

**Pub/Sub + optional list replay (README style):**

```text
                    ┌─────────────────────────────────────┐
                    │              Redis                    │
  Producer ────────►│  PUBLISH m6:dashboard:metrics        │──────► Subscriber A (live)
      │             │  LPUSH + LTRIM m6:dashboard:history │──────► Subscriber B (live)
      │             └─────────────────────────────────────┘
      │                          │
      └─ same metric ─────────────┼──► Late joiner: LRANGE history (last N)
                                 └──► then SUBSCRIBE for live

  Streams-only variant (Lab 6B style):

  Producer ──XADD m6:dashboard:stream MAXLEN ~ N──► Redis stream
                                                      ├──► Dashboard A: XREVRANGE + XREAD
                                                      └──► Dashboard B: XREVRANGE + XREAD
```

---

## 4. Production pitfall — Pub/Sub alone for “payment processed”

**Payments need a durable, auditable record and at-least-once processing.** Pub/Sub is **fire-and-forget**: no persistence on the channel, no ack/retry, subscribers offline during `PUBLISH` **never** see that notification. A worker crash after “processing” but without idempotency can **double-charge** or **never fulfill** if the only signal was Pub/Sub.

**Better:** commit payment in the **database** first; use **outbox**, **stream with consumer groups + XACK**, or a **message queue** for downstream work; Pub/Sub optional for **UI refresh** only after state is already in DB/cache.

---

## Lab takeaways (short)

| Topic | Takeaway |
|-------|----------|
| Pub/Sub | Two TCP roles: subscriber blocks on push; publisher request/reply per `PUBLISH` |
| `MAXLEN ~` | Approximate trim—may keep **more** than N entries on small streams (single macro node) |
| Consumer groups | Split work among workers—not required for “every dashboard sees every metric” |
| Late joiner last N | `XREVRANGE` / `LRANGE` without groups; tail with `XREAD BLOCK` + `last_id` |
