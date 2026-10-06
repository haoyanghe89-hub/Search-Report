from .base import IsolatedSDKAdapter


class AkShareTencentAdapter(IsolatedSDKAdapter):
    provider = "akshare_tencent"
    upstream = "tencent"


class AkShareEastmoneyAdapter(IsolatedSDKAdapter):
    provider = "akshare_eastmoney"
    upstream = "eastmoney"


class AkShareSinaAdapter(IsolatedSDKAdapter):
    provider = "akshare_sina"
    upstream = "sina"
