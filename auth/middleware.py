import os

class AuthMiddleware:
    """
    Injects headers for authenticated scraping.

    Env vars:
      NOVEL_AUTH_BEARER="token..."
      NOVEL_AUTH_COOKIE="name=value; other=value2"
      NOVEL_USER_AGENT="..."
    """

    def __init__(self, bearer: str | None, cookie: str | None, user_agent: str | None):
        self.bearer = bearer
        self.cookie = cookie
        self.user_agent = user_agent

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            bearer=os.getenv("NOVEL_AUTH_BEARER"),
            cookie=os.getenv("NOVEL_AUTH_COOKIE"),
            user_agent=os.getenv("NOVEL_USER_AGENT"),
        )

    def process_request(self, request, spider=None):
        if self.user_agent:
            request.headers.setdefault(b"User-Agent", self.user_agent.encode("utf-8"))
        if self.bearer:
            request.headers[b"Authorization"] = f"Bearer {self.bearer}".encode("utf-8")
        if self.cookie:
            request.headers[b"Cookie"] = self.cookie.encode("utf-8")
        return None
