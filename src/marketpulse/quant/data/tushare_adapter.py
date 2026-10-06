from .base import IsolatedSDKAdapter, ProviderUnavailable


class TushareAdapter(IsolatedSDKAdapter):
    """Reserved P1 port; no account, dependency or SDK call in P0-A/B."""

    provider = "tushare"
    upstream = "tushare"

    async def fetch(self, request, context):
        raise ProviderUnavailable("Tushare is reserved for P1 with explicit entitlement")
