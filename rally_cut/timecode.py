"""타임코드 <-> 초 변환. HH:MM:SS(.mmm), M:S, 또는 bare seconds 허용."""


def parse_tc(text: str) -> float:
    text = str(text).strip()
    if text == "":
        raise ValueError("empty timecode")
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        raise ValueError(f"invalid timecode: {text!r}")
    raise ValueError(f"invalid timecode: {text!r}")


def format_tc(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
