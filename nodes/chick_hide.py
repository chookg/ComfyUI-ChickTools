"""Independent carrier-image encoder node."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..chick.codec import CarrierCodecError, encode_bytes, image_to_png_bytes, required_side
from ..chick.media import audio_to_wav, image_batch, images_to_mp4


class ChickHideNode:
    """Serialize media and return carrier images without network or output-file writes."""

    DESCRIPTION = "将图片、音频或合成视频封装为载体 IMAGE；images 接图片/视频帧，audio 接音频，输出接 ChickSaveImage，保存时不写入 Prompt、工作流或密码元数据。"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "password": ("STRING", {"default": "", "multiline": False,
                                        "tooltip": "载体密码；保存时连接 ChickSaveImage，不使用通用 SaveImage / PreviewImage。"}),
                "title": ("STRING", {"default": "", "multiline": False}),
                "fps": ("INT", {"default": 16, "min": 1, "max": 60, "step": 1}),
                "compress": ([2, 6, 8], {"default": 2}),
                "combine_video": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "images": ("IMAGE",),
                "audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("chick_image",)
    FUNCTION = "encode"
    CATEGORY = "ChickTools/Media"

    def encode(
        self,
        password: str,
        title: str,
        fps: int,
        compress: int,
        combine_video: bool,
        images: Any = None,
        audio: Any = None,
    ) -> tuple[Any]:
        try:
            import torch
            if not all(isinstance(value, str) for value in (password, title)):
                raise CarrierCodecError("password and title must be strings")
            if images is None:
                if audio is None:
                    raise CarrierCodecError("provide images or audio")
                payloads = [(audio_to_wav(audio), "wav")]
            else:
                batch = image_batch(images)
                if audio is not None and not combine_video:
                    raise CarrierCodecError("enable combine_video to include audio with images")
                if combine_video and (len(batch) > 1 or audio is not None):
                    payloads = [(images_to_mp4(batch, fps, audio), "mp4")]
                else:
                    payloads = [(image_to_png_bytes(frame), "png") for frame in batch]
            # Size the headers without encrypting or rendering a disposable carrier.
            side = max(required_side(len(raw) + 6 + len(ext.encode("utf-8")) + (48 if password else 0), compress)
                       for raw, ext in payloads)
            output = torch.empty((len(payloads), side, side, 3), dtype=torch.float32, device="cpu")
            for index, (raw, ext) in enumerate(payloads):
                caption = f"{title} ({index + 1}/{len(payloads)})" if len(payloads) > 1 else title
                carrier = encode_bytes(raw, ext, password, compress, caption, fixed_side=side)
                output[index] = torch.from_numpy(np.asarray(carrier, dtype=np.float32) / 255.0)
            return (output,)
        except (CarrierCodecError, OSError, ValueError) as exc:
            raise RuntimeError(f"[CHICK_HIDE_ERROR] {exc}") from exc
        except ImportError as exc:
            raise RuntimeError("[CHICK_HIDE_ERROR] ComfyUI torch is required") from exc
