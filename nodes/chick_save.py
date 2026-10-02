"""ComfyUI saver for ChickHideNode carriers.

ComfyUI injects the complete original prompt and ``extra_pnginfo`` into every
standard SaveImage node. A ChickHideNode password is an input in that prompt,
so a standard saver can copy the password into PNG tEXt chunks even though the
carrier payload itself is encrypted. This saver forwards only an allowlisted
provenance marker to the host saver.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


try:  # ComfyUI's top-level nodes module is available when the plugin loads.
    from nodes import SaveImage as _ComfySaveImage
except ImportError:  # Keep package registration and unit tests model-free.
    class _ComfySaveImage:  # type: ignore[no-redef]
        @classmethod
        def INPUT_TYPES(cls) -> dict[str, Any]:
            return {"required": {"images": ("IMAGE",), "filename_prefix": ("STRING",)},
                    "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

        def save_images(self, images: Any, filename_prefix: str = "ComfyUI",
                        prompt: Any = None, extra_pnginfo: Any = None) -> dict[str, Any]:
            raise RuntimeError("ComfyUI SaveImage is required to write carriers")


class ChickSaveImage(_ComfySaveImage):
    """Save a Chick carrier without putting the password in PNG metadata."""

    CATEGORY = "ChickTools/Media"
    FUNCTION = "save_images"
    RETURN_TYPES = getattr(_ComfySaveImage, "RETURN_TYPES", ())
    RETURN_NAMES = getattr(_ComfySaveImage, "RETURN_NAMES", RETURN_TYPES)
    OUTPUT_NODE = getattr(_ComfySaveImage, "OUTPUT_NODE", True)
    DESCRIPTION = (
        "保存小鸡载体 PNG；不写入执行 Prompt 或工作流，避免密码进入元数据。"
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        schema = deepcopy(super().INPUT_TYPES())
        hidden = schema.get("hidden")
        if isinstance(hidden, dict):
            hidden.pop("prompt", None)
            if not hidden:
                schema.pop("hidden", None)
        return schema

    def save_images(self, images: Any, filename_prefix: str = "ChickTools/carrier",
                    prompt: Any = None, extra_pnginfo: Any = None, **kwargs: Any) -> Any:
        # Do not mutate the execution graph: ComfyUI may use it for other nodes.
        provenance: dict[str, Any] = {}
        if isinstance(extra_pnginfo, dict) and "AIGC" in extra_pnginfo:
            provenance["AIGC"] = deepcopy(extra_pnginfo["AIGC"])
        return super().save_images(
            images,
            filename_prefix=filename_prefix,
            prompt=None,
            extra_pnginfo=provenance or None,
            **kwargs,
        )
