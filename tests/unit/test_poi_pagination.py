import asyncio

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.amap import AMapClient
from app.tools.budget import RunBudget


@pytest.mark.parametrize("invalid_first", [False, True])
def test_model_requested_candidate_pool_can_exceed_one_api_page(settings, invalid_first):
    settings.amap_web_service_key = "fake"
    pages = []

    async def handler(request):
        page = int(request.url.params["page_num"])
        size = int(request.url.params["page_size"])
        pages.append(page)
        assert size == 25
        rows = [
            {
                "id": f"POI{i}",
                "name": f"咖啡馆{i}",
                "citycode": "0411",
                "cityname": "大连市",
                "location": "" if invalid_first and i == 0 else f"121.5,{38.8 + i * 0.0001}",
            }
            for i in range((page - 1) * size, min(page * size, 30 + invalid_first))
        ]
        return httpx.Response(200, json={"status": "1", "pois": rows})

    budget = RunBudget.create()
    rows = asyncio.run(
        AMapClient(settings, transport=httpx.MockTransport(handler)).search_places(
            keyword="咖啡馆", city="大连市", limit=30, budget=budget
        )
    )
    assert len(rows) == 30 and len({row.poi_id for row in rows}) == 30
    assert pages == [1, 2] and budget.counts["external"] == 2


def test_pagination_cannot_reset_the_original_run_budget(settings):
    settings.amap_web_service_key = "fake"
    calls = []

    async def handler(request):
        calls.append(request.url.params["page_num"])
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "id": f"P{i}",
                        "name": f"店铺{i}",
                        "citycode": "0411",
                        "location": "121.5,38.8",
                    }
                    for i in range(25)
                ],
            },
        )

    budget = RunBudget.create(external=1)
    with pytest.raises(AppError) as error:
        asyncio.run(
            AMapClient(settings, transport=httpx.MockTransport(handler)).search_places(
                keyword="咖啡馆", city="大连市", limit=30, budget=budget
            )
        )
    assert error.value.code == "BUDGET_EXCEEDED" and calls == ["1"]
