"""HTTP transport pinned to the address approved by URL validation."""

import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool

from .url_security import CallbackTarget


class _PinnedAdapter(HTTPAdapter):
    def __init__(self, target: CallbackTarget):
        super().__init__(max_retries=0)
        if target.scheme == "https":
            self.pool = HTTPSConnectionPool(
                target.address, target.port, maxsize=1,
                server_hostname=target.hostname, assert_hostname=target.hostname,
                cert_reqs=ssl.CERT_REQUIRED, ca_certs=requests.certs.where(),
            )
        else:
            self.pool = HTTPConnectionPool(target.address, target.port, maxsize=1)

    def get_connection(self, url, proxies=None):
        return self.pool

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        return self.pool

    def close(self):
        self.pool.close()
        super().close()


def post_completion(target: CallbackTarget, msg: str, timeout: float = 15, *, id: str = "") -> int:
    with requests.Session() as session:
        # Ambient proxies/netrc must not redirect a destination or add credentials.
        session.trust_env = False
        session.mount(f"{target.scheme}://", _PinnedAdapter(target))
        with session.post(
            target.url,
            json={"id": id, "msg": msg},
            headers={"Host": target.authority},
            timeout=timeout, allow_redirects=False, stream=True,
        ) as response:
            # The body is intentionally neither required nor downloaded.
            return response.status_code
