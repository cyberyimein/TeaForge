
from teaforge.naming import source_folder_names


def test_source_folder_names_disambiguates_same_basename(tmp_path):
    first = tmp_path / "accounts" / "user.py"
    second = tmp_path / "billing" / "user.py"

    folders = source_folder_names([first, second])

    assert folders[first.resolve()] == "accounts_user"
    assert folders[second.resolve()] == "billing_user"


def test_source_folder_names_keeps_legacy_basename_when_unique(tmp_path):
    source = tmp_path / "accounts" / "user.py"

    assert source_folder_names([source])[source.resolve()] == "user"
