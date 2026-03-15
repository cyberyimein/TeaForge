import pytest
from fastapi.testclient import TestClient

from demo.fastapi_crud.app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("TEAFORGE_DEMO_DB", str(tmp_path / "demo_test.db"))
    with TestClient(app) as c:
        yield c


@pytest.mark.normal
def test_create_item_normal(client):
    """商品を正常に作成し、参照できること。"""
    response = client.post("/items", json={"name": "tea-green", "quantity": 10})
    assert response.status_code == 200
    item = response.json()
    assert item["name"] == "tea-green"
    assert item["quantity"] == 10


@pytest.mark.boundary
@pytest.mark.parametrize(
    "name",
    ["a", "x" * 50],
    ids=["boundary_min_name", "boundary_max_name"],
)
def test_create_item_boundary_name(client, name):
    """名称の境界値でも作成できること。"""
    response = client.post("/items", json={"name": name, "quantity": 1})
    assert response.status_code == 200
    assert response.json()["name"] == name


@pytest.mark.boundary
@pytest.mark.parametrize(
    "quantity",
    [0, 10_000],
    ids=["boundary_min_quantity", "boundary_max_quantity"],
)
def test_update_item_boundary_quantity(client, quantity):
    """数量の境界値更新が成功すること。"""
    created = client.post("/items", json={"name": f"q-{quantity}", "quantity": 5}).json()
    response = client.put(
        f"/items/{created['id']}",
        json={"name": created["name"], "quantity": quantity},
    )
    assert response.status_code == 200
    assert response.json()["quantity"] == quantity


@pytest.mark.exceptional
def test_create_item_exceptional_duplicate_name(client):
    """重複名称は異常値ケースであること。"""
    first = client.post("/items", json={"name": "dup-tea", "quantity": 3})
    assert first.status_code == 200
    second = client.post("/items", json={"name": "dup-tea", "quantity": 8})
    assert second.status_code == 409
    assert second.json()["detail"] == "Item name already exists"


@pytest.mark.exceptional
def test_get_item_exceptional_not_found(client):
    """存在しない ID の参照は異常値ケースであること。"""
    response = client.get("/items/9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"
