from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from marketpulse.config import Settings


class RobotsPolicy:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self._cache: dict[str, RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._cache:
            robots_url = f"{origin}/robots.txt"
            try:
                response = await self.client.get(
                    robots_url,
                    headers={"User-Agent": self.settings.user_agent},
                    timeout=min(5.0, self.settings.page_timeout_seconds),
                )
                if response.status_code == 404:
                    self._cache[origin] = None
                elif response.is_success:
                    parser = RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(response.text.splitlines())
                    self._cache[origin] = parser
                else:
                    return False
            except httpx.HTTPError:
                return False
        cached_parser = self._cache[origin]
        return (
            True
            if cached_parser is None
            else cached_parser.can_fetch(self.settings.user_agent, url)
        )
