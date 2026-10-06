# Module 0 — Hello Redis (Python + Docker)

## Start Redis

From the repo root:

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml ps
```

## CLI smoke test

```bash
docker exec -it caching-redis redis-cli PING
docker exec -it caching-redis redis-cli SET module0:hello "world" EX 60
docker exec -it caching-redis redis-cli GET module0:hello
docker exec -it caching-redis redis-cli TTL module0:hello
```

## Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python labs/module-0-hello/checkpoint.py
python labs/module-0-hello/hello_redis.py
```

## Stop Redis

```bash
docker compose -f docker/docker-compose.yml down
```

Data persists in the Docker volume `redis-data` until you run `down -v`.
