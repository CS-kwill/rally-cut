"""밴드패스 필터 후 에너지 온셋으로 타구음 시점을 검출한다."""
from typing import List
import numpy as np
from scipy.signal import butter, sosfiltfilt


def _bandpass(x: np.ndarray, sr: int, low: float, high: float) -> np.ndarray:
    nyq = sr / 2.0
    high = min(high, nyq * 0.99)
    sos = butter(4, [low / nyq, high / nyq], btype="band", output="sos")
    return sosfiltfilt(sos, x).astype(np.float32)


def detect_hits(
    x: np.ndarray,
    sr: int,
    low: float = 1500.0,
    high: float = 8000.0,
    frame: float = 0.02,
    min_separation: float = 0.12,
    threshold: float = 6.0,
) -> List[float]:
    """타구음 시점(초) 리스트 반환.

    1) 밴드패스로 바람(저주파) 제거
    2) 프레임 RMS 에너지 포락선 계산
    3) 포락선이 중앙값+threshold*MAD 이상으로 급상승하는 국소 피크를 타격으로
    4) min_separation 이내 중복 피크 제거
    """
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return []

    y = _bandpass(x, sr, low, high)

    hop = max(1, int(frame * sr))
    n_frames = len(y) // hop
    if n_frames == 0:
        return []
    frames = y[: n_frames * hop].reshape(n_frames, hop)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1) + 1e-12)

    # 강건한 임계값: 중앙값 + threshold * MAD
    med = np.median(rms)
    mad = np.median(np.abs(rms - med)) + 1e-12
    thresh = med + threshold * mad

    times: List[float] = []
    last = -1e9
    for i in range(1, n_frames - 1):
        if rms[i] >= thresh and rms[i] >= rms[i - 1] and rms[i] >= rms[i + 1]:
            t = (i * hop) / sr
            if t - last >= min_separation:
                times.append(float(t))
                last = t
    return times
