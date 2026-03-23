from __future__ import annotations

from tools.gimo_server.services.context_indexer import ContextIndexer


def test_extract_file_contents_python_uses_signatures_and_preview(tmp_path):
    file_path = tmp_path / "sample.py"
    file_path.write_text(
        "class Greeter(Base):\n"
        "    def hello(self, name):\n"
        "        return name\n\n"
        "async def main(argv, **kwargs):\n"
        "    return argv\n",
        encoding="utf-8",
    )

    content = ContextIndexer.extract_file_contents(str(tmp_path), ["sample.py"])

    assert "--- sample.py ---" in content
    assert "[Python signatures]" in content
    assert "class Greeter(Base)" in content
    assert "def hello(self, name)" in content
    assert "async def main(argv, **kwargs)" in content
    assert "[First 100 lines]" in content


def test_extract_file_contents_python_invalid_ast_falls_back_to_preview(tmp_path):
    file_path = tmp_path / "broken.py"
    file_path.write_text("def broken(:\n    pass\n", encoding="utf-8")

    content = ContextIndexer.extract_file_contents(str(tmp_path), ["broken.py"])

    assert "--- broken.py ---" in content
    assert "[Python signatures]" not in content
    assert "def broken(" in content


def test_extract_file_contents_non_python_is_truncated_to_first_100_lines(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("\n".join(f"line {idx}" for idx in range(1, 151)), encoding="utf-8")

    content = ContextIndexer.extract_file_contents(str(tmp_path), ["notes.txt"])

    assert "--- notes.txt ---" in content
    assert "line 1" in content
    assert "line 100" in content
    assert "line 101" not in content


def test_extract_file_contents_blocks_paths_outside_workspace_even_with_shared_prefix(tmp_path):
    sibling = tmp_path.parent / f"{tmp_path.name}_sibling"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("SECRET", encoding="utf-8")

    content = ContextIndexer.extract_file_contents(str(tmp_path), [f"../{sibling.name}/secret.txt"])

    assert "[Access denied: Path outside workspace]" in content
    assert "SECRET" not in content


def test_extract_file_contents_reports_missing_files(tmp_path):
    content = ContextIndexer.extract_file_contents(str(tmp_path), ["missing.txt"])

    assert "--- missing.txt ---" in content
    assert "[File not found]" in content
