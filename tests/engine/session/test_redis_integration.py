import os
from uuid import uuid4

import pytest
from redis import Redis

from callbot.engine.errors import CallBusy
from callbot.engine.session.redis_store import RedisSessionStore
from callbot.engine.session.store import SessionRecord


@pytest.fixture
def real_redis_store():
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        if os.getenv("REQUIRE_REDIS_TESTS") == "1":
            pytest.fail("REQUIRE_REDIS_TESTS=1 nhưng thiếu TEST_REDIS_URL")
        pytest.skip("TEST_REDIS_URL chưa được cấu hình")
    client = Redis.from_url(url, decode_responses=True)
    prefix = f"integration:{uuid4().hex}"
    store = RedisSessionStore(client, key_prefix=prefix, close_client=False)
    try:
        store.check_ready()
        yield store
    finally:
        for key in client.scan_iter(match=f"{prefix}:*"):
            client.delete(key)
        client.close()


def test_real_redis_shares_session_and_distributed_lock(real_redis_store) -> None:
    first = real_redis_store
    second = RedisSessionStore(
        Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True),
        key_prefix=first._prefix,
    )
    try:
        first.create_session(
            SessionRecord(
                call_id="c_real",
                start_config={"call_id": "c_real"},
                opening={"utterance": "Xin chào"},
                context={"state": "AWAITING_IDENTITY"},
            )
        )
        assert second.get_session("c_real").opening == {"utterance": "Xin chào"}

        with first.call_lock("c_real", 0.1):
            with pytest.raises(CallBusy):
                with second.call_lock("c_real", 0.05):
                    pass
    finally:
        second.close()
