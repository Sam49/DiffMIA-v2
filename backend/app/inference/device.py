"""Device selection: auto-detects CUDA / MPS / CPU when torch is available."""
from __future__ import annotations


def detect_device(requested: str = "auto") -> str:
    """Return a concrete device label. Falls back to cpu when torch is absent."""
    if requested and requested != "auto":
        return requested
    try:
        import torch  # noqa: F401
    except Exception:
        return "cpu"
    try:
        import torch  # noqa: F401

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def gpu_status() -> dict:
    """Basic GPU observability (empty when torch/CUDA is unavailable)."""
    info: dict = {"available": False, "devices": []}
    try:
        import torch  # noqa: F401
    except Exception:
        return info
    if not torch.cuda.is_available():
        return info
    info["available"] = True
    for index in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(index)
        info["devices"].append(
            {
                "index": index,
                "name": props.name,
                "memory_gb": round(props.total_memory / (1024**3), 2),
            }
        )
    try:
        info["current_device"] = torch.cuda.current_device()
    except Exception:
        pass
    return info
