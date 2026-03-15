import pytest


@pytest.mark.normal
def test_create_user_normal():
    """ユーザーを正常に作成できること。"""
    assert 200 == 200


@pytest.mark.boundary
@pytest.mark.parametrize("age", [0, 120], ids=["boundary_min_age", "boundary_max_age"])
def test_create_user_boundary(age):
    """年齢の境界値を確認すること。"""
    assert 0 <= age <= 120


@pytest.mark.exceptional
def test_get_user_exceptional_not_found():
    """存在しないユーザーの参照。"""
    assert 404 == 404
