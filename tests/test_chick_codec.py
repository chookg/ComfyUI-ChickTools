from io import BytesIO
import unittest

import numpy as np
from PIL import Image
import torch

from plugin_loader import plugin
from chicktools.chick.codec import CarrierCodecError, decode_bytes, encode_bytes, image_to_png_bytes


class CarrierCodecTests(unittest.TestCase):
    def setUp(self):
        self.source = Image.new("RGB", (8, 8), (12, 34, 56))
        output = BytesIO()
        self.source.save(output, format="PNG")
        self.raw = output.getvalue()

    def test_round_trip_all_lsb_widths(self):
        for compress in (2, 6, 8):
            with self.subTest(compress=compress):
                carrier = encode_bytes(self.raw, "png", compress=compress, title="sample")
                self.assertGreaterEqual(carrier.width, 640)
                recovered, extension = decode_bytes(carrier)
                self.assertEqual((recovered, extension), (self.raw, "png"))

    def test_password_round_trip_and_rejection(self):
        carrier = encode_bytes(self.raw, "png", password="local-test", compress=6)
        self.assertEqual(decode_bytes(carrier, "local-test"), (self.raw, "png"))
        with self.assertRaises(CarrierCodecError):
            decode_bytes(carrier)
        with self.assertRaises(CarrierCodecError):
            decode_bytes(carrier, "wrong")

    def test_large_payload_across_bit_chunk_boundaries_and_png_save(self):
        raw = bytes(range(256)) * 1200 + b"\x00\x00"
        for width in (2, 6, 8):
            with self.subTest(width=width):
                carrier = encode_bytes(raw, "bin", password="chunks", compress=width)
                output = BytesIO()
                carrier.save(output, format="PNG")
                with Image.open(BytesIO(output.getvalue())) as saved:
                    self.assertEqual(decode_bytes(saved, "chunks"), (raw, "bin"))

    def test_image_conversion_rejects_batches(self):
        with self.assertRaises(CarrierCodecError):
            image_to_png_bytes(np.zeros((2, 8, 8, 3), dtype=np.float32))

    def test_node_encodes_a_real_image_batch(self):
        source = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
        source[:, :, :, 0] = 0.25
        carrier = plugin.NODE_CLASS_MAPPINGS["ChickHideNode"]().encode(
            password="node-test", title="", fps=24, compress=2, combine_video=False, images=source
        )[0]
        self.assertEqual(tuple(carrier.shape[:1]), (1,))
        carrier_image = Image.fromarray(np.rint(carrier[0].numpy() * 255).astype(np.uint8), mode="RGB")
        recovered, extension = decode_bytes(carrier_image, "node-test")
        self.assertEqual(extension, "png")
        with Image.open(BytesIO(recovered)) as restored:
            self.assertEqual(restored.size, (8, 8))
            self.assertEqual(restored.getpixel((0, 0)), (64, 0, 0))
