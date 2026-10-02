"""HTTP text notification, independent from media inputs and the codec."""

from typing import Any

import requests

from ..utils.callback_http import post_completion
from ..utils.url_security import CallbackURLValidationError, validate_callback_url


class AnyType(str):
    def __ne__(self, other: object) -> bool:
        return False


ANY_TYPE = AnyType("*")


class NotifyMeNode:
    DESCRIPTION = "向 callback_url 发送 JSON：{\"id\":\"任务编号\",\"msg\":\"上游文本\"}。id 可手动填写；msg 是可选 STRING 输入；passthrough 可接收并原样输出任意类型。仅 HTTP 200 成功。"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {
            "callback_url": ("STRING", {"default": "", "multiline": False}),
        }, "optional": {
            "msg": ("STRING", {"forceInput": True}),
            "passthrough": (ANY_TYPE, {"forceInput": True}),
            "allow_localhost": ("BOOLEAN", {"default": False, "advanced": True,
                "tooltip": "本地测试时开启，允许 127.0.0.1 或 ::1 回调；默认关闭。"}),
            "id": ("STRING", {"default": "", "multiline": False,
                "tooltip": "任务编号，随 msg 原样发送到回调地址；留空时发送空字符串。"}),
        }}

    RETURN_TYPES = (ANY_TYPE,)
    RETURN_NAMES = ("passthrough",)
    FUNCTION = "notify"
    CATEGORY = "ChickTools/Network"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Each queued run notifies again even if its upstream text is cached.
        return float("nan")

    def notify(self, callback_url: str, msg: str = "", allow_localhost: bool = False,
               passthrough: Any = None, id: str = "") -> tuple[Any, ...]:
        if not isinstance(callback_url, str) or not callback_url.strip():
            raise Exception("请输入有效的回调地址")
        if not isinstance(msg, str):
            raise Exception("请输入有效的文本消息（msg 必须为文本）")
        if not isinstance(id, str):
            raise Exception("请输入有效的任务编号（id 必须为文本）")
        if not isinstance(allow_localhost, bool):
            raise Exception("allow_localhost 必须为布尔值")
        try:
            target = validate_callback_url(callback_url, allow_localhost=allow_localhost)
            status = post_completion(target, msg, timeout=15, id=id)
        except CallbackURLValidationError as exc:
            raise Exception(f"请输入有效的回调地址：{exc}") from exc
        except (requests.RequestException, OSError, ValueError) as exc:
            # Avoid echoing URLs which may contain private callback query tokens.
            raise Exception(f"回调请求失败（{type(exc).__name__}）") from exc
        if status != 200:
            raise Exception(f"回调请求失败（HTTP {status}）")
        return (passthrough,)
