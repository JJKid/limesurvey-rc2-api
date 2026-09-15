import asyncio
from unittest.mock import AsyncMock

from infrastructure import redis_client


def test_redis_tls_verifies_certificate_and_hostname(monkeypatch):
    client = AsyncMock()
    factory = lambda **kwargs: client
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return factory(**kwargs)

    monkeypatch.setattr(redis_client.redis, "Redis", capture)
    monkeypatch.setattr(redis_client, "REDIS_SSL", True)
    monkeypatch.setattr(redis_client, "REDIS_USERNAME", "fastapi")
    monkeypatch.setattr(redis_client, "REDIS_SSL_CA_CERTS", "/run/redis-ca/ca.crt")
    async def verify():
        await redis_client.initialize_redis()
        try:
            assert captured["username"] == "fastapi"
            assert captured["ssl_cert_reqs"] == "required"
            assert captured["ssl_check_hostname"] is True
            assert captured["ssl_ca_certs"] == "/run/redis-ca/ca.crt"
            client.ping.assert_awaited_once()
        finally:
            await redis_client.close_redis()

    asyncio.run(verify())
