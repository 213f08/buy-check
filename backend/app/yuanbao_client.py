"""元宝搜索客户端（买前尽调版）：双认证模式。

1. **API Key 模式**（推荐，零依赖）：对应官方「服务 API KEY 方式」文档——
   POST https://api.wsa.cloud.tencent.com/SearchPro
   Headers: Authorization: Bearer <YUANBAO_API_KEY>
   Body: {"Query": "..."}（若服务端拒绝附加参数，自动降级为仅 Query）
2. **AK/SK 模式**：腾讯云 SDK `tencentcloud-sdk-python`（wsa / SearchPro）。
3. 无任何密钥时进入 mock 模式（报告由 catalog 精选数据生成）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Optional

try:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.wsa.v20250508 import models, wsa_client

    _HAS_SDK = True
except Exception:  # pragma: no cover
    _HAS_SDK = False

ALLOWED_CNT = (10, 20, 30, 40, 50)
API_KEY_ENDPOINT = "https://api.wsa.cloud.tencent.com/SearchPro"

# 进程级记忆：API Key 端点是否拒绝附加参数（Cnt/Mode）
_ENDPOINT_MINIMAL_ONLY: Optional[bool] = None


def snap_cnt(cnt: int) -> int:
    for allowed in ALLOWED_CNT:
        if cnt <= allowed:
            return allowed
    return 50


@dataclass
class SearchPage:
    title: str
    passage: str
    url: str = ""
    site: str = ""
    date: str = ""
    score: float = 0.0
    authority_level: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_pages(payload: dict) -> list[SearchPage]:
    """统一解析 Pages[]（每条是 JSON 字符串，必须逐条反序列化）。"""
    response = payload.get("Response") or payload
    pages: list[SearchPage] = []
    for raw in (response.get("Pages") or []):
        data = json.loads(raw) if isinstance(raw, str) else raw
        pages.append(SearchPage(
            title=str(data.get("title") or ""),
            passage=str(data.get("passage") or data.get("content") or ""),
            url=str(data.get("url") or ""),
            site=str(data.get("site") or ""),
            date=str(data.get("date") or ""),
            score=float(data.get("score") or 0.0),
            authority_level=str(data.get("authority_level") or ""),
        ))
    return pages


def _raise_tc_error(payload: dict) -> None:
    response = payload.get("Response") or {}
    error = response.get("Error") or (payload.get("Error") if isinstance(payload, dict) else None)
    if error:
        raise RuntimeError(
            f"{error.get('Code', 'UnknownError')}: {error.get('Message', '')}"
        )


class YuanbaoSearchClient:
    def __init__(self, mock: Optional[bool] = None) -> None:
        self.api_key = os.getenv("YUANBAO_API_KEY", "")
        self.secret_id = os.getenv("TENCENTCLOUD_SECRET_ID", "")
        self.secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY", "")
        self.region = os.getenv("TENCENTCLOUD_REGION", "")

        if self.api_key:
            self.auth = "api-key"
        elif self.secret_id and self.secret_key:
            self.auth = "aksk"
        else:
            self.auth = "none"

        if mock is None:
            mock = os.getenv("MOCK", "0") == "1" or self.auth == "none"
        self.mock = bool(mock) or (self.auth == "aksk" and not _HAS_SDK)

    @classmethod
    def from_env(cls) -> "YuanbaoSearchClient":
        return cls()

    @property
    def mode(self) -> str:
        return "mock" if self.mock else "live"

    def search(
        self,
        query: str,
        cnt: int = 10,
        industry: Optional[str] = None,
        freshness: Optional[str] = None,
        site: Optional[str] = None,
    ) -> list[SearchPage]:
        if not query.strip():
            return []
        cnt = snap_cnt(cnt)
        if self.mock:
            return []
        if self.auth == "api-key":
            return self._apikey_search(query, cnt)
        return self._aksk_search(query, cnt, industry, freshness, site)

    # ------------------------------------------------------------------
    # API Key 模式（零依赖，标准库直连）
    # ------------------------------------------------------------------
    def _apikey_search(self, query: str, cnt: int) -> list[SearchPage]:
        global _ENDPOINT_MINIMAL_ONLY

        attempts = [{"Query": query}]
        if not _ENDPOINT_MINIMAL_ONLY:
            attempts.insert(0, {"Query": query, "Cnt": cnt, "Mode": 2})

        last_error: Optional[Exception] = None
        for body in attempts:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                API_KEY_ENDPOINT,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                _raise_tc_error(data)
                _ENDPOINT_MINIMAL_ONLY = (len(body) == 1)
                return _parse_pages(data)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                last_error = RuntimeError(f"HTTP {exc.code}: {detail}")
                # 参数被拒绝（400 类）→ 尝试最小参数重试；其他错误直接抛出
                if exc.code < 400 or exc.code >= 500 or len(body) == 1:
                    raise last_error from exc
            except RuntimeError as exc:
                last_error = exc
                if len(body) == 1:
                    raise
                # 业务错误（参数类）→ 尝试最小参数重试
                if not _looks_like_param_error(str(exc)):
                    raise

        raise last_error or RuntimeError("SearchPro 请求失败")

    @staticmethod
    def _looks_like_param_error(message: str) -> bool:
        lowered = message.lower()
        return any(k in lowered for k in (
            "param", "invalid", "unsupported", "unknown", "not support",
        ))

    # ------------------------------------------------------------------
    # AK/SK 模式（腾讯云 SDK）
    # ------------------------------------------------------------------
    def _aksk_search(
        self,
        query: str,
        cnt: int,
        industry: Optional[str],
        freshness: Optional[str],
        site: Optional[str],
    ) -> list[SearchPage]:
        if not _HAS_SDK:
            raise RuntimeError("未安装 tencentcloud-sdk-python，无法使用 AK/SK 模式")
        cred = credential.Credential(self.secret_id, self.secret_key)
        http_profile = HttpProfile(endpoint="wsa.tencentcloudapi.com")
        client = wsa_client.WsaClient(
            cred, self.region, ClientProfile(httpProfile=http_profile)
        )
        req = models.SearchProRequest()
        req.Query = query
        req.Mode = 2          # 坑：Mode=1 会静默返回空数组
        req.Cnt = cnt         # 坑：只能是 10/20/30/40/50
        if industry:
            req.Industry = industry
        if freshness:
            req.Freshness = freshness
        if site:
            req.Site = site

        resp = client.SearchPro(req)
        pages: list[SearchPage] = []
        for raw in (getattr(resp, "Pages", None) or []):
            data = json.loads(raw) if isinstance(raw, str) else raw
            pages.append(SearchPage(
                title=str(data.get("title") or ""),
                passage=str(data.get("passage") or data.get("content") or ""),
                url=str(data.get("url") or ""),
                site=str(data.get("site") or ""),
                date=str(data.get("date") or ""),
                score=float(data.get("score") or 0.0),
                authority_level=str(data.get("authority_level") or ""),
            ))
        return pages
