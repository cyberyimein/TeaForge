import pytest
from fastapi.testclient import TestClient

from demo.fastapi_crud.app.main import _db_path, app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("TEAFORGE_DEMO_DB", str(tmp_path / "demo_test.db"))
    with TestClient(app) as c:
        yield c


@pytest.mark.normal
def test_list_items_normal(client):
    """商品一覧が作成順に取得できること。"""
    first = client.post("/items", json={"name": "list-green", "quantity": 2}).json()
    second = client.post("/items", json={"name": "list-black", "quantity": 4}).json()

    response = client.get("/items")

    assert response.status_code == 200
    assert response.json() == [first, second]


@pytest.mark.normal
def test_db_path_defaults_without_env(monkeypatch):
    """環境変数が無い場合はデフォルト DB パスを返すこと。"""
    monkeypatch.delenv("TEAFORGE_DEMO_DB", raising=False)

    assert _db_path().name == "demo.db"
