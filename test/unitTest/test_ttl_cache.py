"""The `ttl_cache` decorator's contract (KAN-53).

Before `cache_if`, the only way a decorated function could decline to be cached was to return
None, because `TTLCache.get` used None to mean "no entry". Every provider wrapper here fails by
returning a value instead -- an empty frame, an approximated rate -- so the failure was stored
and served for the full hour, turning a momentary outage into an hour-long one.

The decorator writes to the module-level `cache` singleton rather than a per-function store, so
every test empties it either side.
"""
import unittest

from backend.app.core.cache import cache, ttl_cache


class Counted:
    """A function that records its calls and can be told what to return.

    `__name__` is part of the cache key, so it has to be present and distinct per function.
    """

    def __init__(self, result=None, name="inner"):
        self.calls = 0
        self.result = result
        self.__name__ = name

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.result


class TTLCacheCase(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)


class TestCacheIfGatesStorage(TTLCacheCase):
    def test_an_accepted_result_is_served_without_calling_through(self):
        inner = Counted(result="good")
        cached = ttl_cache(cache_if=lambda r: r == "good")(inner)

        self.assertEqual([cached("x"), cached("x")], ["good", "good"])
        self.assertEqual(inner.calls, 1)

    def test_a_refused_result_is_returned_to_this_caller_but_not_kept(self):
        # The caller still gets the degraded answer -- the endpoint must keep responding. It is
        # only the *next* caller who must not be handed it.
        inner = Counted(result="failed")
        cached = ttl_cache(cache_if=lambda r: r != "failed")(inner)

        self.assertEqual(cached("x"), "failed")
        self.assertEqual(cached("x"), "failed")
        self.assertEqual(inner.calls, 2)

    def test_a_refused_result_leaves_the_key_free_rather_than_occupying_it(self):
        inner = Counted(result="failed")
        cached = ttl_cache(cache_if=lambda r: False)(inner)
        cached("x")

        self.assertEqual(cache._store, {})

    def test_recovery_is_immediate_rather_than_waiting_for_the_ttl(self):
        # The whole point of the ticket: a transient failure followed by a healthy provider.
        inner = Counted(result="failed")
        cached = ttl_cache(ttl=3600, cache_if=lambda r: r != "failed")(inner)
        self.assertEqual(cached("VUSA.L"), "failed")

        inner.result = "recovered"
        self.assertEqual(cached("VUSA.L"), "recovered")
        self.assertEqual(cached("VUSA.L"), "recovered")
        # Two calls, not three: the failure was retried and the recovery then took the key.
        self.assertEqual(inner.calls, 2)

    def test_the_predicate_sees_the_result_not_the_arguments(self):
        seen = []
        inner = Counted(result=(None, "GBP"))
        cached = ttl_cache(cache_if=lambda r: seen.append(r) or True)(inner)
        cached("VUSA.L", "2024-01-01")

        self.assertEqual(seen, [(None, "GBP")])


class TestWithoutAPredicate(TTLCacheCase):
    def test_every_result_is_cached_when_no_predicate_is_given(self):
        inner = Counted(result="anything")
        cached = ttl_cache()(inner)
        cached("x")
        cached("x")

        self.assertEqual(inner.calls, 1)

    def test_a_falsy_result_is_cached_rather_than_re_fetched(self):
        # Emptiness is a real answer -- a delisted ticker returns no closes -- so the decorator
        # must not treat it as a failure of its own accord.
        inner = Counted(result=[])
        cached = ttl_cache()(inner)
        cached("DEAD")
        cached("DEAD")

        self.assertEqual(inner.calls, 1)

    def test_a_result_of_none_is_cached_and_served(self):
        # This is the overload the ticket traces the defect to: a stored None used to be
        # indistinguishable from an absent key, so such a function was silently never cached.
        inner = Counted(result=None)
        cached = ttl_cache()(inner)
        self.assertIsNone(cached("x"))
        self.assertIsNone(cached("x"))

        self.assertEqual(inner.calls, 1)


class TestKeyingAndExpiry(TTLCacheCase):
    def test_different_arguments_do_not_share_an_entry(self):
        inner = Counted(result="v")
        cached = ttl_cache()(inner)
        cached("AAPL", "2024-01-01")
        cached("AAPL", "2020-06-01")
        cached("MSFT", "2024-01-01")

        self.assertEqual(inner.calls, 3)

    def test_two_decorated_functions_do_not_collide_on_one_singleton(self):
        first = Counted(result="first", name="first")
        second = Counted(result="second", name="second")

        self.assertEqual(ttl_cache()(first)("x"), "first")
        self.assertEqual(ttl_cache()(second)("x"), "second")

    def test_an_expired_entry_is_fetched_again(self):
        inner = Counted(result="v")
        cached = ttl_cache(ttl=-1)(inner)
        cached("x")
        cached("x")

        self.assertEqual(inner.calls, 2)

    def test_reading_an_expired_entry_drops_it(self):
        cache.set("k", "v", ttl=-1)
        cache.get("k")

        self.assertEqual(cache._store, {})


class TestGetDefault(TTLCacheCase):
    def test_an_absent_key_returns_the_caller_s_default(self):
        sentinel = object()

        self.assertIs(cache.get("nothing-here", sentinel), sentinel)
        self.assertIsNone(cache.get("nothing-here"))

    def test_a_stored_none_is_returned_rather_than_the_default(self):
        sentinel = object()
        cache.set("k", None)

        self.assertIsNone(cache.get("k", sentinel))


class TestInvalidation(TTLCacheCase):
    def test_delete_removes_single_key(self):
        cache.set("k", "v")
        self.assertTrue(cache.delete("k"))
        self.assertFalse(cache.delete("k"))
        self.assertIsNone(cache.get("k"))

    def test_wrapper_clear_all_for_function(self):
        inner = Counted(result="v")
        cached = ttl_cache()(inner)
        cached("arg1")
        cached("arg2")
        self.assertEqual(inner.calls, 2)

        cached("arg1")
        self.assertEqual(inner.calls, 2)

        cached.clear()
        cached("arg1")
        self.assertEqual(inner.calls, 3)

    def test_wrapper_clear_specific_signature(self):
        inner = Counted(result="v")
        cached = ttl_cache()(inner)
        cached("arg1")
        cached("arg2")
        self.assertEqual(inner.calls, 2)

        cached.clear("arg1")
        cached("arg2")
        self.assertEqual(inner.calls, 2)
        cached("arg1")
        self.assertEqual(inner.calls, 3)

    def test_wrapper_invalidate_alias(self):
        inner = Counted(result="v")
        cached = ttl_cache()(inner)
        cached()
        self.assertEqual(inner.calls, 1)
        cached.invalidate()
        cached()
        self.assertEqual(inner.calls, 2)


if __name__ == "__main__":
    unittest.main()
