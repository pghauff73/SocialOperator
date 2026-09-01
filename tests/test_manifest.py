from pathlib import Path

from socialoperator.manifest import build_source_manifest


def test_manifest_is_stable_for_same_source(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.txt").write_text("beta")
    first = build_source_manifest(tmp_path)
    second = build_source_manifest(tmp_path)
    assert first["root"] == "."
    assert first["entries_sha256"] == second["entries_sha256"]
    assert first["entry_count"] == 2


def test_manifest_excludes_private_runtime_directories(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("source")
    (tmp_path / "data" / "private").mkdir(parents=True)
    (tmp_path / "data" / "private" / "secret.txt").write_text("secret")
    manifest = build_source_manifest(tmp_path)
    paths = [entry["path"] for entry in manifest["entries"]]
    assert paths == ["source.txt"]
