import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATH = PROJECT_ROOT / "auth" / "storage_state.json"


class StorageStateCookieMiddleware:
    def process_request(self, request, spider):
        if not STORAGE_PATH.exists():
            return

        state = json.loads(STORAGE_PATH.read_text(encoding="utf-8"))
        cookies = state.get("cookies", [])

        cookie_header = "; ".join(
            f"{c['name']}={c['value']}"
            for c in cookies
        )

        if cookie_header:
            request.headers.setdefault("Cookie", cookie_header)
