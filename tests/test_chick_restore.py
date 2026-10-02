from io import BytesIO
import unittest

import numpy as np
from PIL import Image
import torch

from plugin_loader import plugin
from chicktools.chick.codec import encode_bytes


class RestoreImageTests(unittest.TestCase):
    def test_restores_rgb_and_rgba_batches_pixel_for_pixel(self):
        encoder = plugin.NODE_CLASS_MAPPINGS["ChickHideNode"]()
        decoder = plugin.NODE_CLASS_MAPPINGS["ChickRestoreImage"]()
        for channels in (3, 4):
            source = torch.arange(2 * 8 * 12 * channels).reshape(2, 8, 12, channels).remainder(256).float() / 255
            for compress in (2, 6, 8):
                with self.subTest(channels=channels, compress=compress):
                    carrier, = encoder.encode("roundtrip", "", 8, compress, False, source)
                    restored, = decoder.restore(carrier, "roundtrip")
                    torch.testing.assert_close(restored, source, rtol=0, atol=0)

    def test_wrong_password_and_non_image_payload_fail(self):
        decoder = plugin.NODE_CLASS_MAPPINGS["ChickRestoreImage"]()
        buffer = BytesIO()
        Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
        for raw, extension, password, expected in (
            (buffer.getvalue(), "png", "wrong", "password"),
            (b"synthetic video payload", "mp4", "secret", "PNG payload"),
        ):
            carrier = np.asarray(encode_bytes(raw, extension, "secret"))[None]
            with self.subTest(extension=extension), self.assertRaisesRegex(RuntimeError, expected):
                decoder.restore(carrier, password)

    def test_plain_image_is_not_silently_treated_as_a_carrier(self):
        decoder = plugin.NODE_CLASS_MAPPINGS["ChickRestoreImage"]()
        with self.assertRaisesRegex(RuntimeError, "CHICK_RESTORE_ERROR"):
            decoder.restore(torch.zeros((1, 16, 16, 3)))
