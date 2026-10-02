"""Resolve once, reject non-public destinations, and keep the approved address."""

from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


class CallbackURLValidationError(ValueError):
    """A callback URL failed validation."""


@dataclass(frozen=True)
class CallbackTarget:
    url: str
    hostname: str
    address: str
    port: int
    scheme: str
    authority: str


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _public_address(str(address.ipv4_mapped))
        if address.sixtofour or address.teredo or address in ipaddress.ip_network("64:ff9b::/96"):
            return False
    return address.is_global and not (address.is_multicast or address.is_reserved)


def validate_callback_url(callback_url: str, *, allow_localhost: bool = False) -> CallbackTarget:
    value = (callback_url or "").strip()
    if not value:
        raise CallbackURLValidationError("未填写 callback_url")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise CallbackURLValidationError("callback_url 包含无效字符")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise CallbackURLValidationError("callback_url 仅允许 http:// 或 https://")
        if not parsed.hostname:
            raise CallbackURLValidationError("callback_url 缺少主机名")
        if parsed.username is not None or parsed.password is not None:
            raise CallbackURLValidationError("callback_url 不允许携带用户名或密码")
        if parsed.fragment:
            raise CallbackURLValidationError("callback_url 不允许 URL fragment")
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if "%" in hostname or hostname == "localhost" or hostname.endswith(".localhost") or hostname == "metadata.google.internal":
            raise CallbackURLValidationError("callback_url 不允许本机或 metadata 地址")
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if port == 0:
            raise CallbackURLValidationError("callback_url 端口无效")
        try:
            addresses = [str(ipaddress.ip_address(hostname))]
        except ValueError:
            addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(
                hostname, port, type=socket.SOCK_STREAM
            )))
        local_test = allow_localhost is True and hostname in {"127.0.0.1", "::1"}
        if not local_test and (not addresses or not all(_public_address(address) for address in addresses)):
            raise CallbackURLValidationError("callback_url 仅允许公网地址")
        host = f"[{hostname}]" if ":" in hostname else hostname
        authority = f"{host}:{port}" if parsed.port is not None else host
        normalized = urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))
        return CallbackTarget(normalized, hostname, addresses[0], port, parsed.scheme, authority)
    except CallbackURLValidationError:
        raise
    except (ValueError, UnicodeError, OSError) as exc:
        raise CallbackURLValidationError("callback_url 格式无效或 DNS 解析失败") from exc
