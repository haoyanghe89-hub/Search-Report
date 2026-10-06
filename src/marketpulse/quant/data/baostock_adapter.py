from .base import IsolatedSDKAdapter


class BaoStockAdapter(IsolatedSDKAdapter):
    provider = "baostock"
    upstream = "baostock"
