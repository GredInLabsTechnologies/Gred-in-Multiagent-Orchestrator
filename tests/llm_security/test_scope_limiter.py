from tools.llm_security.scope_limiter import ScopeLimiter


def test_filter_files_by_extension(tmp_path):
    allowed = tmp_path / "test.py"
    denied = tmp_path / "test.exe"
    allowed.touch()
    denied.touch()

    files, reasons = ScopeLimiter.filter_files([allowed, denied])
    assert allowed in files
    assert denied not in files
    assert any("Extension not allowed" in r for r in reasons)


def test_filter_files_by_path(tmp_path):
    # Use lowercase/normalized paths for comparison consistency if needed,
    # but the implementation uses path.suffix and simple string check.
    secret_path = tmp_path / ".env"
    secret_path.touch()

    files, reasons = ScopeLimiter.filter_files([secret_path])
    assert secret_path not in files
    assert any("Path in denylist" in r for r in reasons)


def test_filter_files_max_limit(tmp_path):
    paths = [tmp_path / f"file{i}.py" for i in range(15)]
    for p in paths:
        p.touch()

    allowed, denied = ScopeLimiter.filter_files(paths)
    assert len(allowed) == ScopeLimiter.MAX_FILES
    assert any("Max files limit reached" in d for d in denied)


def test_truncate_content():
    content = "token " * 3000  # ~3000 tokens
    # MAX_TOTAL_TOKENS = 8000 (32000 chars approx)
    content = "A" * (8000 * 4 + 100)
    truncated = ScopeLimiter.truncate_content(content)
    assert len(truncated) < len(content)
    assert "[... CONTENT TRUNCATED FOR SAFETY ...]" in truncated


def test_filter_files_large_file(tmp_path):
    large_file = tmp_path / "large.py"
    large_file.write_bytes(b"A" * (ScopeLimiter.MAX_BYTES_PER_FILE + 1))

    files, reasons = ScopeLimiter.filter_files([large_file])
    assert large_file not in files
    assert any("File too large" in r for r in reasons)
