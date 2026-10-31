"""限流器单元测试（注入假时钟，不 sleep）。"""
import unittest

from backend.app.hardening import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class TestRateLimiter(unittest.TestCase):
    def test_allows_up_to_max_then_denies(self):
        clock = FakeClock()
        rl = SlidingWindowRateLimiter(3, 60, now_fn=clock)
        self.assertTrue(all(rl.allow("ip1") for _ in range(3)))
        self.assertFalse(rl.allow("ip1"))

    def test_keys_independent(self):
        clock = FakeClock()
        rl = SlidingWindowRateLimiter(1, 60, now_fn=clock)
        self.assertTrue(rl.allow("a"))
        self.assertFalse(rl.allow("a"))
        self.assertTrue(rl.allow("b"))

    def test_window_expiry_restores(self):
        clock = FakeClock()
        rl = SlidingWindowRateLimiter(2, 60, now_fn=clock)
        rl.allow("ip")
        rl.allow("ip")
        self.assertFalse(rl.allow("ip"))
        clock.advance(61)
        self.assertTrue(rl.allow("ip"))

    def test_retry_after_positive_and_decays(self):
        clock = FakeClock()
        rl = SlidingWindowRateLimiter(1, 60, now_fn=clock)
        rl.allow("ip")
        self.assertFalse(rl.allow("ip"))
        first = rl.retry_after("ip")
        self.assertGreaterEqual(first, 1)
        clock.advance(30)
        self.assertLess(rl.retry_after("ip"), first)

    def test_prune_keeps_memory_bounded(self):
        clock = FakeClock()
        rl = SlidingWindowRateLimiter(1, 60, now_fn=clock, max_keys=5)
        for i in range(50):
            clock.advance(10)  # 让旧 key 陆续过期，触发清理
            rl.allow(f"ip{i}")
        self.assertLessEqual(len(rl._hits), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
