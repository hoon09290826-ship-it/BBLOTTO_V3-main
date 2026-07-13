import os
import sys
import uvicorn


def _read_port() -> int:
    raw = (os.environ.get("PORT") or "8000").strip()
    try:
        return int(raw)
    except ValueError:
        print(f"[BBLOTTO] Invalid PORT value {raw!r}; falling back to 8000", file=sys.stderr)
        return 8000


if __name__ == "__main__":
    port = _read_port()
    print(f"[BBLOTTO] Starting backend.app:app on 0.0.0.0:{port}", flush=True)
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port)
