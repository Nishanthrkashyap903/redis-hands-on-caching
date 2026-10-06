# Module 1 — Core data types & when to use them

**Prerequisites:** Module 0 done (Docker Redis up, venv, `redis` client). Comfortable with `redis-cli` basics from `redis-commands-playground.md`.

**Goal:** Pick the right Redis type for a small problem, design keys clearly, implement three tiny Python CLIs (or one script with subcommands—your choice).

**Prefix:** Use `m1:` on all keys (e.g. `m1:views:/home`) so you can clean up with `SCAN m1:`*.

---

## Before you code — key design (Step 1.6)

Create `notes/key-conventions.md` in the repo root with **your** rules, for example:

- Pattern: `{app}:{entity}:{id}` or `{app}:{purpose}:{...}`
- When you use Hash vs JSON string
- Max length for lists you trim

You will refine this in later modules; start with 5–10 lines.

---



## Lab 1A — Page view counter per URL

**Story:** Each time someone “views” a URL, increment a counter. You can simulate views from Python (loop or input).

**Requirements:**

- Different URLs get **independent** counts.
- Reading a URL’s count should not reset it.
- Safe if two “requests” happen at once (think: why `INCR` matters).

**Hints:**

- URL strings can contain `/` and `?` — consider **hashing** the URL for the key suffix, or a safe encoding, so keys stay predictable and not huge.
- Command family: `INCR` (or `INCRBY` for batch simulate).
- Optional: `GET` after `INCR` to print the new total.

**CLI idea:** `python lab_1a_views.py hit /blog/post-1` and `python lab_1a_views.py stats /blog/post-1`

**Verify in redis-cli:** `GET` or whatever structure you chose — be able to explain your key name aloud.

---



## Lab 1B — User profile hash (partial updates)

**Story:** Cache a user as fields (`name`, `email`, `login_count`). Update **one field** without rewriting the whole object.

**Requirements:**

- Create user `42` (or any id) with at least 3 fields.
- Update only `email` (or `name`) — other fields unchanged.
- Increment `login_count` atomically.

**Hints:**

- One Redis **key** per user; fields inside a **Hash**.
- Commands: `HSET`, `HGET`, `HGETALL`, `HINCRBY`.
- Compare mentally: one `SET` of a JSON string vs Hash — which fields does each approach update?

**CLI idea:** `set`, `show`, `bump-login` subcommands.

---



## Lab 1C — Top-10 leaderboard

**Story:** Players earn points; show the top 10 by score.

**Requirements:**

- Add/update scores for several players (same player adding points again should **increase** score, not duplicate rows).
- Print top 10 highest scores with player id and score.
- Handle ties gracefully (same score — order is OK as Redis defines it).

**Hints:**

- **Sorted set:** member = player id, score = points.
- `ZINCRBY` for “add 50 points to player_x”.
- `ZREVRANGE ... WITHSCORES` for top N.

**CLI idea:** `add-points player_a 100`, `top`

---



## Suggested layout (you create the files)

```text
labs/module-1-data-types/
  README.md          # this file
  lab_1a_views.py    # you write
  lab_1b_profile.py  # you write
  lab_1c_leaderboard.py
```

Reuse connection setup from Module 0 (`REDIS_URL`, `decode_responses=True`).

---



## Module 1 checkpoint (write in `notes/module-1-checkpoint.md`)

For **each lab**, answer in your own words:

1. Which **caching read/write pattern** is this closest to? (e.g. cache-aside write of aggregate stats, materialized counter, etc.) — perfection not required; reasoning matters.
2. If Redis **restarts empty** mid-day, what does the user see for counts / profiles / leaderboard?
3. Would you add a **TTL** to these keys in production? Why or why not?

---



## Order of work

1. Skim playground sections 1, 4, 7 again (strings, hashes, sorted sets).
2. Write `notes/key-conventions.md`.
3. Lab 1A → 1B → 1C (CLI or single entrypoint).
4. Checkpoint doc.
5. Tell your instructor: **“Module 1 done”** or ask for hints on a **specific** stuck point (paste command/error, not “give me the code”).

---



## Stuck? Hint ladder

1. Reproduce the smallest case in `redis-cli` only.
2. Check `TYPE yourkey` — wrong type → `WRONGTYPE` in Python.
3. `TTL key` — did you expect expiry? (Module 1 often has **no** TTL on purpose; note that in checkpoint.)
4. Ask for a hint with: lab id, what you tried, actual vs expected behavior.

