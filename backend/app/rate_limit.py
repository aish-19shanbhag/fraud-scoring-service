"""Fixed-window rate limiter stored in Redis (per client IP, per minute)."""

import time

from fastapi import HTTPException, Request, status


def rate_limit(request: Request) -> None:
    limit = request.app.state.settings.rate_limit_per_minute
    if limit <= 0:  # 0 disables rate limiting
        return

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = int(now // 60)
    key = f"ratelimit:{client_ip}:{window}"

    pipe = request.app.state.redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, 65)
    count, _ = pipe.execute()

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({limit} requests/minute)",
            headers={"Retry-After": str(60 - int(now) % 60)},
        )
