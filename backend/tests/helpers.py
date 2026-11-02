"""測試用 API 輔助。後續 Task 會在這裡擴充寫入標頭、快照等方法。"""

from typing import Any

import httpx
from fastapi.testclient import TestClient


class ApiClient:
    """包一層 TestClient，讓測試以一致的方式呼叫 API。"""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.put(path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.patch(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.delete(path, **kwargs)
