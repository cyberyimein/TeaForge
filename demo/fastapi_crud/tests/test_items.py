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
    ids=["boundary_min_name_inside", "boundary_max_name_inside"],
)
def test_create_item_boundary_name_inside(client, name):
    """名称の境界内値でも作成できること。"""
    response = client.post("/items", json={"name": name, "quantity": 1})

    assert response.status_code == 200
    assert response.json()["name"] == name


@pytest.mark.boundary
@pytest.mark.parametrize(
    "quantity",
    [0, 10_000],
    ids=["boundary_min_quantity_inside", "boundary_max_quantity_inside"],
)
def test_create_item_boundary_quantity_inside(client, quantity):
    """数量の境界内値でも作成できること。"""
    response = client.post("/items", json={"name": f"create-{quantity}", "quantity": quantity})

    assert response.status_code == 200
    assert response.json()["quantity"] == quantity


@pytest.mark.boundary
@pytest.mark.parametrize(
    ("name", "quantity", "field"),
    [
        ("", 1, "name"),
        ("x" * 51, 1, "name"),
        ("quantity-low", -1, "quantity"),
        ("quantity-high", 10_001, "quantity"),
    ],
    ids=[
        "boundary_outside_min_name",
        "boundary_outside_max_name",
        "boundary_outside_min_quantity",
        "boundary_outside_max_quantity",
    ],
)
def test_create_item_boundary_outside_validation(client, name, quantity, field):
    """名称や数量が境界外の場合はバリデーションエラーになること。"""
    response = client.post("/items", json={"name": name, "quantity": quantity})

    assert response.status_code == 422
    assert any(error["loc"][-1] == field for error in response.json()["detail"])


@pytest.mark.exceptional
def test_create_item_exceptional_duplicate_name(client):
    """重複名称は異常値ケースであること。"""
    first = client.post("/items", json={"name": "dup-tea", "quantity": 3})
    second = client.post("/items", json={"name": "dup-tea", "quantity": 8})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Item name already exists"


@pytest.mark.normal
def test_get_item_normal(client):
    """作成済み商品の参照が成功すること。"""
    created = client.post("/items", json={"name": "get-tea", "quantity": 4}).json()
    response = client.get(f"/items/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.exceptional
def test_get_item_exceptional_not_found(client):
    """存在しない ID の参照は異常値ケースであること。"""
    response = client.get("/items/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"


@pytest.mark.normal
def test_update_item_normal(client):
    """既存商品の更新が正常に成功すること。"""
    created = client.post("/items", json={"name": "update-normal", "quantity": 5}).json()
    response = client.put(
        f"/items/{created['id']}",
        json={"name": "update-renamed", "quantity": 7},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "update-renamed"
    assert updated["quantity"] == 7


@pytest.mark.boundary
@pytest.mark.parametrize(
    "quantity",
    [0, 10_000],
    ids=["boundary_min_quantity_inside", "boundary_max_quantity_inside"],
)
def test_update_item_boundary_quantity_inside(client, quantity):
    """数量の境界内値更新が成功すること。"""
    created = client.post("/items", json={"name": f"q-{quantity}", "quantity": 5}).json()
    response = client.put(
        f"/items/{created['id']}",
        json={"name": created["name"], "quantity": quantity},
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == quantity


@pytest.mark.boundary
@pytest.mark.parametrize(
    ("name", "quantity", "field"),
    [
        ("", 1, "name"),
        ("x" * 51, 1, "name"),
        ("update-low", -1, "quantity"),
        ("update-high", 10_001, "quantity"),
    ],
    ids=[
        "boundary_outside_min_name",
        "boundary_outside_max_name",
        "boundary_outside_min_quantity",
        "boundary_outside_max_quantity",
    ],
)
def test_update_item_boundary_outside_validation(client, name, quantity, field):
    """更新値が境界外の場合はバリデーションエラーになること。"""
    created = client.post("/items", json={"name": f"seed-{field}", "quantity": 5}).json()
    response = client.put(
        f"/items/{created['id']}",
        json={"name": name, "quantity": quantity},
    )

    assert response.status_code == 422
    assert any(error["loc"][-1] == field for error in response.json()["detail"])


@pytest.mark.exceptional
def test_update_item_exceptional_duplicate_name(client):
    """別商品の名称と重複する更新は異常値であること。"""
    client.post("/items", json={"name": "dup-source", "quantity": 2})
    target = client.post("/items", json={"name": "dup-target", "quantity": 6}).json()
    response = client.put(
        f"/items/{target['id']}",
        json={"name": "dup-source", "quantity": 9},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Item name already exists"


@pytest.mark.exceptional
def test_update_item_exceptional_not_found(client):
    """存在しない商品更新は異常値ケースであること。"""
    response = client.put(
        "/items/9999",
        json={"name": "missing-item", "quantity": 1},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"


@pytest.mark.normal
def test_delete_item_normal(client):
    """既存商品の削除が成功すること。"""
    created = client.post("/items", json={"name": "delete-tea", "quantity": 3}).json()
    response = client.delete(f"/items/{created['id']}")
    fetch_deleted = client.get(f"/items/{created['id']}")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    assert fetch_deleted.status_code == 404


@pytest.mark.exceptional
def test_delete_item_exceptional_not_found(client):
    """存在しない商品の削除は異常値ケースであること。"""
    response = client.delete("/items/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"
