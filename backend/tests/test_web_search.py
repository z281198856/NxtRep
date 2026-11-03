import json

import httpx
import pytest

from nxtrep_backend.core.config import Settings
from nxtrep_backend.services.web_search import WebSearchService


@pytest.fixture(autouse=True)
def empty_public_cache():
    from nxtrep_backend.services.web_search import _PUBLIC_CACHE

    _PUBLIC_CACHE.clear()
    yield
    _PUBLIC_CACHE.clear()


def make_service(handler, **options):
    return WebSearchService(
        Settings(_env_file=None, glm_api_key="private-test-key", **options),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_web_search_sends_only_public_query_and_returns_real_excerpt_sources():
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["search_query"] == "双层吉士汉堡 营养"
        assert body["search_domain_filter"] == "mcdonalds.com.cn"
        assert "user_id" not in body and "messages" not in body
        return httpx.Response(
            200,
            json={
                "search_result": [
                    {
                        "title": "双层吉士汉堡",
                        "link": "https://www.mcdonalds.com.cn/product/x",
                        "content": "每份营养",
                    },
                    {
                        "title": "重复",
                        "link": "https://www.mcdonalds.com.cn/product/x",
                        "content": "每份营养",
                    },
                    {"title": "伪链接", "link": "javascript:alert(1)", "content": "不应显示"},
                    {"title": "空正文", "link": "https://example.com", "content": ""},
                ]
            },
        )

    service = make_service(handler)
    first = await service.search("双层吉士汉堡 营养", "mcdonalds.com.cn")
    assert first["status"] == "available"
    assert len(first["sources"]) == 1
    assert first["sources"][0]["evidence_type"] == "search_excerpt"
    assert first["searched_at"]
    cached = await service.search("双层吉士汉堡 营养", "mcdonalds.com.cn")
    assert cached["sources"] == first["sources"]
    assert cached["searched_at"] == first["searched_at"]
    assert cached["cache_hit"] is True
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [(401, "WEB_SEARCH_ACCESS_DENIED"), (429, "WEB_SEARCH_BUSY"), (503, "WEB_SEARCH_FAILED")],
)
async def test_search_errors_never_expose_provider_credentials_or_body(status, code):
    service = make_service(
        lambda request: httpx.Response(status, json={"error": "private-test-key SQL raw response"})
    )
    result = await service.search("训练恢复研究")
    assert result["error_code"] == code
    assert result["sources"] == []
    assert "private-test-key" not in json.dumps(result)
    assert "SQL" not in json.dumps(result)


@pytest.mark.asyncio
async def test_search_timeout_preserves_distinct_public_reason():
    def handler(request):
        raise httpx.ReadTimeout("private-test-key", request=request)

    result = await make_service(handler).search("训练恢复研究")
    assert result["error_code"] == "WEB_SEARCH_TIMEOUT"


@pytest.mark.asyncio
async def test_search_budget_prevents_unbounded_external_calls():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"search_result": []})

    service = make_service(handler)
    for query in ["训练", "饮食", "恢复"]:
        assert (await service.search(query))["status"] == "no_evidence"
    assert (await service.search("第四次查询"))["error_code"] == "WEB_SEARCH_LIMIT"
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"search_result": None}, ["invalid"]])
async def test_incomplete_response_cannot_be_presented_as_web_evidence(payload):
    result = await make_service(lambda request: httpx.Response(200, json=payload)).search("训练")
    assert result["error_code"] == "WEB_SEARCH_RESULT_INVALID"


@pytest.mark.asyncio
async def test_disabled_search_and_private_query_make_no_network_request():
    def unexpected(request):
        pytest.fail("This request must not leave the backend")

    service = make_service(unexpected, web_search_enabled=False)
    assert (await service.search("训练"))["error_code"] == "WEB_SEARCH_DISABLED"
    assert (await service.search("邮箱 athlete@example.com"))["error_code"] == "WEB_QUERY_PRIVATE"


@pytest.mark.asyncio
async def test_public_cache_is_shared_bounded_expires_and_can_be_refreshed(monkeypatch):
    import nxtrep_backend.services.web_search as web

    calls = []
    now = [0.0]
    monkeypatch.setattr(web, "monotonic", lambda: now[0])
    monkeypatch.setattr(web, "PUBLIC_CACHE_MAX_ENTRIES", 2)

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "search_result": [
                    {
                        "title": "研究",
                        "link": "https://example.org/study",
                        "content": "公开摘要",
                    }
                ]
            },
        )

    first = await make_service(handler).search("cache-one")
    cached = await make_service(handler).search("cache-one")
    assert cached["cache_hit"] and len(calls) == 1
    assert cached["searched_at"] == first["searched_at"]
    assert not (await make_service(handler).search("cache-one", refresh=True))["cache_hit"]
    assert len(calls) == 2
    now[0] = 901.0
    assert not (await make_service(handler).search("cache-one"))["cache_hit"]
    await make_service(handler).search("cache-two")
    await make_service(handler).search("cache-three")
    assert len(web._PUBLIC_CACHE) == 2
    assert (await make_service(handler, web_search_enabled=False).search("cache-three"))[
        "error_code"
    ] == "WEB_SEARCH_DISABLED"


@pytest.mark.asyncio
async def test_failure_is_not_shared_across_chats():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    assert (await make_service(handler).search("temporary-error"))["status"] == "unavailable"
    assert (await make_service(handler).search("temporary-error"))["status"] == "unavailable"
    assert len(calls) == 2
