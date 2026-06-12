import numpy as np
import pytest


@pytest.fixture
def sr():
    return 22050


def _click(n, sr, t):
    """t초 위치에 짧은 고주파 클릭(타구음 모사)을 더한 인덱스 범위 반환."""
    i = int(t * sr)
    length = int(0.01 * sr)  # 10ms
    return i, length


@pytest.fixture
def make_signal(sr):
    def _make(hit_times, with_wind=True, dur=10.0):
        n = int(dur * sr)
        x = np.zeros(n, dtype=np.float32)
        if with_wind:
            # 저주파 바람: 200Hz 이하 컬러드 노이즈 근사
            t = np.arange(n) / sr
            rng = np.random.RandomState(0)
            wind = rng.randn(n).astype(np.float32)
            # 간단한 이동평균 저역통과
            k = 200
            wind = np.convolve(wind, np.ones(k) / k, mode="same").astype(np.float32)
            x += 0.5 * wind
        for ht in hit_times:
            i, length = _click(n, sr, ht)
            tt = np.arange(length) / sr
            click = np.sin(2 * np.pi * 4000 * tt).astype(np.float32)
            env = np.exp(-tt / 0.003).astype(np.float32)
            seg = (click * env)
            x[i:i + length] += seg[: max(0, min(length, n - i))]
        return x
    return _make
