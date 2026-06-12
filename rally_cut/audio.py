"""ffmpeg로 영상에서 모노 wav 오디오를 추출한다."""
from typing import List, Tuple
import numpy as np
from scipy.io import wavfile
from .ffmpeg_run import run_ffmpeg


def build_extract_cmd(src: str, dst_wav: str, sr: int = 22050) -> List[str]:
    return [
        "ffmpeg", "-y",
        "-i", src,
        "-vn",                 # 비디오 제거
        "-ac", "1",            # mono
        "-ar", str(sr),        # 샘플레이트
        "-f", "wav",
        dst_wav,
    ]


def extract_audio(src: str, dst_wav: str, sr: int = 22050) -> Tuple[int, np.ndarray]:
    """추출 후 (samplerate, float32 mono [-1,1]) 반환."""
    cmd = build_extract_cmd(src, dst_wav, sr)
    run_ffmpeg(cmd)
    out_sr, data = wavfile.read(dst_wav)
    if data.ndim > 1:
        data = data.mean(axis=1)
    # 정수 PCM -> float[-1,1]
    if np.issubdtype(data.dtype, np.integer):
        max_val = float(np.iinfo(data.dtype).max)
        data = data.astype(np.float32) / max_val
    else:
        data = data.astype(np.float32)
    return out_sr, data
