"""Простий rate limit на основі кешу Django (кеш у БД — спільний для всіх воркерів)."""

import hashlib

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    if settings.USE_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        # Беремо останню адресу: її додав довірений проксі; попередні клієнт може підробити.
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.META.get("REMOTE_ADDR", "")


def _key(scope, *parts):
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"rl:{scope}:{digest}"


def is_limited(scope, limit, *parts):
    """Чи вичерпано ліміт (без інкременту)."""
    return cache.get(_key(scope, *parts), 0) >= limit


def hit(scope, window, *parts):
    """Зареєструвати спробу; повертає поточну кількість у вікні."""
    key = _key(scope, *parts)
    if cache.add(key, 1, window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # ключ щойно протух
        cache.set(key, 1, window)
        return 1


def reset(scope, *parts):
    cache.delete(_key(scope, *parts))


def throttle(scope, seconds, *parts):
    """Дозволити дію не частіше ніж раз на `seconds`. True — можна, False — зарано."""
    return cache.add(_key(scope, *parts), 1, seconds)
