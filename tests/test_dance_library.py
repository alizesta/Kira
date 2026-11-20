from kira import dance_library, vrm_vendor


def test_scan_picks_supported_files(tmp_path):
    (tmp_path / "b.VRMA").write_bytes(b"x")
    (tmp_path / "a one.fbx").write_bytes(b"x")
    (tmp_path / "empty.fbx").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("hi")
    items = dance_library.scan(tmp_path)
    assert [i["name"] for i in items] == ["a one", "b"]
    assert items[0]["kind"] == "fbx" and items[0]["url"] == "animations/a%20one.fbx"
    assert items[1]["kind"] == "vrma"


def test_scan_missing_folder(tmp_path):
    assert dance_library.scan(tmp_path / "nope") == []


def test_optional_vendor_not_required():
    assert not set(vrm_vendor.OPTIONAL) & set(vrm_vendor.FILES)
