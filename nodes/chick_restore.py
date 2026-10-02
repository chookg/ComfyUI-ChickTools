"""Restore image pixels from Chick carrier images for downstream preview or processing."""

from io import BytesIO

import numpy as np
from PIL import Image

from ..chick.codec import CarrierCodecError, decode_bytes, image_pixels
from ..chick.media import image_batch


class ChickRestoreImage:
    DESCRIPTION = "从小鸡载体中还原 PNG 图片，输出原图 IMAGE。密码须与编码时一致；视频和音频请使用本地结果页解码。"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "chick_image": ("IMAGE",),
            "password": ("STRING", {"default": "", "multiline": False}),
        }}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "restore"
    CATEGORY = "ChickTools/Media"

    def restore(self, chick_image, password=""):
        import torch

        try:
            if not isinstance(password, str):
                raise CarrierCodecError("password must be a string")
            restored = []
            for frame in image_batch(chick_image):
                raw, extension = decode_bytes(Image.fromarray(image_pixels(frame)), password)
                if extension != "png":
                    raise CarrierCodecError("image restoration requires a PNG payload; use the local viewer for video/audio")
                with Image.open(BytesIO(raw)) as image:
                    pixels = np.array(image.convert("RGBA" if "A" in image.getbands() else "RGB"), dtype=np.float32) / 255.0
                if restored and pixels.shape != restored[0].shape:
                    raise CarrierCodecError("restored images must have matching dimensions and channels")
                restored.append(pixels)
            return (torch.from_numpy(np.stack(restored)),)
        except (CarrierCodecError, OSError, ValueError) as exc:
            raise RuntimeError(f"[CHICK_RESTORE_ERROR] {exc}") from exc
