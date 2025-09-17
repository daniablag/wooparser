from __future__ import annotations
from typing import List, Optional, Dict, Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .config import Settings, get_settings
from .utils import RateLimiter, get_logger

logger = get_logger("wc")

class WooClient:
    def __init__(self, base_url: str, api_version: str, auth: httpx.Auth | tuple[str, str], timeout: int = 30, rate_limit_rps: float = 0.5) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.auth = auth
        self.timeout = timeout
        self.rate_limiter = RateLimiter(rate_limit_rps)

    @classmethod
    def from_settings(cls, s: Settings | None = None) -> "WooClient":
        s = s or get_settings()
        if s.wc_consumer_key and s.wc_consumer_secret:
            auth: httpx.Auth | tuple[str, str] = (s.wc_consumer_key, s.wc_consumer_secret)
        elif s.wp_user and s.wp_app_password:
            auth = httpx.BasicAuth(s.wp_user, s.wp_app_password)
        else:
            raise ValueError("Нужны либо WC_CONSUMER_* либо WP_USER+WP_APP_PASSWORD")
        return cls(base_url=s.wp_base_url, api_version=s.wc_api_version, auth=auth, timeout=s.requests_timeout, rate_limit_rps=s.rate_limit_rps)

    def _wc_url(self, endpoint: str) -> str:
        return f"{self.base_url}/wp-json/{self.api_version}/{endpoint.lstrip(/)}"

    def _wp_url(self, endpoint: str) -> str:
        return f"{self.base_url}/wp-json/wp/v2/{endpoint.lstrip(/)}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def _request(self, method: str, url: str, *, json: Optional[dict] = None, params: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
        self.rate_limiter.wait()
        with httpx.Client(auth=self.auth, timeout=self.timeout, headers=headers) as client:
            resp = client.request(method, url, json=json, params=params)
            if resp.status_code >= 400:
                logger.error("HTTP %s %s -> %s %s", method, url, resp.status_code, resp.text[:200])
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            return resp.json() if "json" in ct or resp.text.startswith("{") else resp.text

    # Products
    def create_product(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", self._wc_url("products"), json=payload)

    def update_product(self, product_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PUT", self._wc_url(f"products/{product_id}"), json=payload)

    def find_product_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        items = self._request("GET", self._wc_url("products"), params={"sku": sku})
        return items[0] if isinstance(items, list) and items else None

    def upsert_variable_product(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sku = payload.get("sku")
        if sku:
            found = self.find_product_by_sku(sku)
            if found:
                return self.update_product(found["id"], payload)
        return self.create_product(payload)

    def create_variations(self, product_id: int, payload_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        # batch endpoint
        return self._request("POST", self._wc_url(f"products/{product_id}/variations/batch"), json={"create": payload_list})

    # Attributes
    def ensure_global_attribute(self, name: str) -> int:
        attrs = self._request("GET", self._wc_url("products/attributes"))
        for a in attrs:
            if a.get("name") == name:
                return a["id"]
        created = self._request("POST", self._wc_url("products/attributes"), json={"name": name, "type": "select"})
        return created["id"]

    def ensure_attribute_terms(self, attr_id: int, options: List[str]) -> List[int]:
        existing = self._request("GET", self._wc_url(f"products/attributes/{attr_id}/terms"))
        existing_names = {t["name"]: t["id"] for t in existing}
        ids: List[int] = []
        for opt in options:
            if opt in existing_names:
                ids.append(existing_names[opt])
            else:
                created = self._request("POST", self._wc_url(f"products/attributes/{attr_id}/terms"), json={"name": opt})
                ids.append(created["id"])
        return ids

    # Media (via WP REST)
    def post_media_binary(self, filename: str, data: bytes, alt: str = "") -> Dict[str, Any]:
        headers = {"Content-Type": "application/octet-stream", "Content-Disposition": f"attachment; filename={filename}"}
        res = self._request("POST", self._wp_url("media"), headers=headers, json=None)  # placeholder
        # Для простоты минимального E2E не загружаем бинарники
        return {"id": 0, "source_url": ""}
