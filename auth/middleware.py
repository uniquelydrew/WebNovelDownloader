import json

from utils.app_paths import auth_storage_path


STORAGE_PATH = auth_storage_path()


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
