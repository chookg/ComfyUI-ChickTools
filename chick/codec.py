"""Lossless carrier codec used by ChickHideNode.

The carrier is a lossless RGB PNG. A four-byte big-endian header length is
stored first, followed by a binary file header and its payload. The header
contains an optional password marker, extension and payload length.
"""

from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest
from io import BytesIO
from numbers import Integral
from pathlib import Path
import os
import struct
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont


SKIP_W_RATIO = 0.40
SKIP_H_RATIO = 0.08
CHANNELS = 3
MINIMUM_SIDE = 640
SUPPORTED_LSB_BITS = (2, 6, 8)


class CarrierCodecError(ValueError):
    """Raised when a carrier cannot be encoded or decoded."""


def _key_stream(password: str, salt: bytes, length: int) -> bytes:
    material = (password + salt.hex()).encode("utf-8")
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(sha256(material + str(counter).encode("ascii")).digest())
        counter += 1
    return bytes(output[:length])


def _protect(raw: bytes, password: str) -> tuple[bytes, bytes, bytes, bool]:
    if not password:
        return raw, b"", b"", False
    salt = os.urandom(16)
    check = sha256((password + salt.hex()).encode("utf-8")).digest()
    stream = _key_stream(password, salt, len(raw))
    return bytes(left ^ right for left, right in zip(raw, stream)), salt, check, True


def build_file_header(raw: bytes, password: str, extension: str) -> bytes:
    extension = extension.lstrip(".")
    extension_bytes = extension.encode("utf-8")
    if not extension_bytes or len(extension_bytes) > 255:
        raise CarrierCodecError("extension must contain 1-255 UTF-8 bytes")
    protected, salt, check, has_password = _protect(raw, password)
    header = bytearray((1 if has_password else 0,))
    if has_password:
        header.extend(check)
        header.extend(salt)
    header.append(len(extension_bytes))
    header.extend(extension_bytes)
    header.extend(struct.pack(">I", len(protected)))
    header.extend(protected)
    return bytes(header)


def parse_file_header(header: bytes, password: str = "") -> tuple[bytes, str]:
    if len(header) < 1:
        raise CarrierCodecError("carrier header is empty")
    cursor = 1
    has_password = header[0] == 1
    if header[0] not in (0, 1):
        raise CarrierCodecError("carrier password marker is invalid")
    check = salt = b""
    if has_password:
        if len(header) < cursor + 48:
            raise CarrierCodecError("carrier password header is truncated")
        check = header[cursor:cursor + 32]
        salt = header[cursor + 32:cursor + 48]
        cursor += 48
    if len(header) < cursor + 1:
        raise CarrierCodecError("carrier extension is missing")
    extension_length = header[cursor]
    cursor += 1
    if len(header) < cursor + extension_length + 4:
        raise CarrierCodecError("carrier metadata is truncated")
    try:
        extension = header[cursor:cursor + extension_length].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CarrierCodecError("carrier extension is invalid") from exc
    cursor += extension_length
    payload_length = struct.unpack(">I", header[cursor:cursor + 4])[0]
    cursor += 4
    payload = header[cursor:]
    if len(payload) != payload_length:
        raise CarrierCodecError("carrier payload length does not match")
    if not has_password:
        return payload, extension
    if not password:
        raise CarrierCodecError("password is required")
    expected = sha256((password + salt.hex()).encode("utf-8")).digest()
    if not compare_digest(expected, check):
        raise CarrierCodecError("password is incorrect")
    stream = _key_stream(password, salt, len(payload))
    return bytes(left ^ right for left, right in zip(payload, stream)), extension


def _lsb_bits(compress: int) -> int:
    if isinstance(compress, bool) or not isinstance(compress, Integral) or compress not in SUPPORTED_LSB_BITS:
        raise CarrierCodecError("compress must be 2, 6 or 8")
    return int(compress)


def _channel_count(height: int, width: int) -> int:
    return (height * width - int(height * SKIP_H_RATIO) * int(width * SKIP_W_RATIO)) * CHANNELS


def _channel_chunks(array):
    """Yield writable row-major views, omitting the reserved rectangle."""
    height, width, _ = array.shape
    skip_h, skip_w = int(height * SKIP_H_RATIO), int(width * SKIP_W_RATIO)
    flat = array.reshape(-1)
    spans = ((row * width * 3 + skip_w * 3, (row + 1) * width * 3) for row in range(skip_h))
    for start, stop in spans:
        yield flat[start:stop]
    for start in range(skip_h * width * 3, len(flat), 65536):
        yield flat[start:start + 65536]


def required_side(header_length: int, compress: int, minimum: int = MINIMUM_SIDE) -> int:
    bits = _lsb_bits(compress)
    side = max(MINIMUM_SIDE, int(minimum))
    needed = (header_length + 4) * 8
    while _channel_count(side, side) * bits < needed:
        side += 64
    return side


def _embed(canvas: Image.Image, header: bytes, compress: int) -> Image.Image:
    bits_per_channel = _lsb_bits(compress)
    payload = struct.pack(">I", len(header)) + header
    array = np.array(canvas.convert("RGB"), dtype=np.uint8)
    if len(payload) * 8 > _channel_count(*array.shape[:2]) * bits_per_channel:
        raise CarrierCodecError("carrier capacity is too small")
    keep_mask = np.uint8(255 ^ ((1 << bits_per_channel) - 1))
    weights = 1 << np.arange(bits_per_channel - 1, -1, -1, dtype=np.uint8)
    position = 0
    for channels in _channel_chunks(array):
        count = min(len(channels), (len(payload) * 8 - position + bits_per_channel - 1) // bits_per_channel)
        if count <= 0:
            break
        end = min(position + count * bits_per_channel, len(payload) * 8)
        bits = np.unpackbits(np.frombuffer(payload[position // 8:(end + 7) // 8], dtype=np.uint8))
        bits = bits[position % 8:position % 8 + end - position]
        bits = np.pad(bits, (0, count * bits_per_channel - len(bits)))
        values = (bits.reshape(count, bits_per_channel) * weights).sum(axis=1).astype(np.uint8)
        channels[:count] = (channels[:count] & keep_mask) | values
        position += count * bits_per_channel
    return Image.fromarray(array)


def extract_file_header(image: Image.Image, compress: int) -> bytes:
    bits_per_channel = _lsb_bits(compress)
    array = np.array(image.convert("RGB"), dtype=np.uint8)
    output, pending = bytearray(), np.empty(0, dtype=np.uint8)
    total_bytes = None
    for channels in _channel_chunks(array):
        values = channels & ((1 << bits_per_channel) - 1)
        bits = np.unpackbits(values).reshape(-1, 8)[:, -bits_per_channel:].reshape(-1)
        bits = np.concatenate((pending, bits))
        end = len(bits) // 8 * 8
        output.extend(np.packbits(bits[:end]).tobytes())
        pending = bits[end:]
        if total_bytes is None and len(output) >= 4:
            total_bytes = 4 + struct.unpack(">I", output[:4])[0]
            if total_bytes <= 4 or total_bytes * 8 > _channel_count(*array.shape[:2]) * bits_per_channel:
                raise CarrierCodecError("carrier header length is invalid")
        if total_bytes is not None and len(output) >= total_bytes:
            return bytes(output[4:total_bytes])
    raise CarrierCodecError("carrier is too small")


def decode_bytes(image: Image.Image, password: str = "") -> tuple[bytes, str]:
    errors = []
    for compress in SUPPORTED_LSB_BITS:
        try:
            return parse_file_header(extract_file_header(image, compress), password)
        except CarrierCodecError as exc:
            errors.append(str(exc))
    raise CarrierCodecError("carrier decode failed: " + "; ".join(errors))


def _make_canvas(side: int, title: str) -> Image.Image:
    image = Image.new("RGB", (side, side), (255, 248, 233))
    with Image.open(Path(__file__).resolve().parents[1] / "assets" / "chick.png") as source:
        cover = source.convert("RGBA").resize((side, side), Image.Resampling.LANCZOS)
    image.paste(cover, (0, 0), cover.getchannel("A"))
    draw = ImageDraw.Draw(image)
    if title:
        font = ImageFont.load_default()
        draw.text((int(side * .05), int(side * .04)), title[:40], fill=(20, 40, 50), font=font)
    return image


def encode_bytes(raw: bytes, extension: str, password: str = "", compress: int = 2,
                 title: str = "", fixed_side: Optional[int] = None) -> Image.Image:
    header = build_file_header(raw, password, extension)
    side = required_side(len(header), compress, fixed_side or MINIMUM_SIDE)
    return _embed(_make_canvas(side, title), header, compress)


def image_pixels(image: object) -> np.ndarray:
    if hasattr(image, "detach"):
        image = image.detach().cpu()
        image = (image.float() if image.is_floating_point() else image).numpy()
    array = np.asarray(image)
    if array.ndim == 4:
        if array.shape[0] != 1:
            raise CarrierCodecError("image_to_png_bytes accepts one frame")
        array = array[0]
    if array.ndim != 3 or array.shape[-1] not in (3, 4) or min(array.shape) < 1:
        raise CarrierCodecError("images must have shape HxWx3 or HxWx4")
    if array.dtype.kind not in "fiu" or not np.isfinite(array).all():
        raise CarrierCodecError("image pixels must be finite numbers")
    if np.issubdtype(array.dtype, np.floating):
        array = np.rint(np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    else:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return array


def image_to_png_bytes(image: object) -> bytes:
    image = Image.fromarray(image_pixels(image))
    output = BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=9)
    return output.getvalue()
