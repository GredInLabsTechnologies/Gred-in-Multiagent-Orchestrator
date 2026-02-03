import pytest

from tools.llm_security.cache import LLMResponseCache


class TestLLMResponseCache:
    @pytest.fixture
    def cache_dir(self, tmp_path):
        return tmp_path / "llm_cache"

    def test_cache_key_generation(self, cache_dir):
        cache = LLMResponseCache(cache_dir)
        key1 = cache.get_cache_key("code1", "security")
        key2 = cache.get_cache_key("code1", "security")
        key3 = cache.get_cache_key("code2", "security")

        assert key1 == key2
        assert key1 != key3

    def test_cache_get_miss(self, cache_dir):
        cache = LLMResponseCache(cache_dir)
        assert cache.get("none", "none") is None

    def test_cache_set_and_hit(self, cache_dir):
        cache = LLMResponseCache(cache_dir)
        code = "print('hello')"
        atype = "quality"
        result = {"response": "Looks good", "metadata": {"tokens": 10}, "success": True}

        cache.set(code, atype, result)
        cached = cache.get(code, atype)

        assert cached is not None
        assert cached["result"] == "Looks good"
        assert cached["metadata"]["tokens"] == 10
        assert "cached_at" in cached

    def test_cache_only_successful(self, cache_dir):
        cache = LLMResponseCache(cache_dir)
        code = "fail"
        cache.set(code, "type", {"success": False, "response": "error"})
        assert cache.get(code, "type") is None

    def test_cache_persistence(self, cache_dir):
        cache1 = LLMResponseCache(cache_dir)
        cache1.set("persist", "type", {"success": True, "response": "data"})

        cache2 = LLMResponseCache(cache_dir)
        assert cache2.get("persist", "type")["result"] == "data"
