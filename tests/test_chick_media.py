"""Small CPU-only media tests; PyAV independently inspects the generated MP4."""

from io import BytesIO
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import wave

import av
import numpy as np
from PIL import Image
import torch

from plugin_loader import plugin
from chicktools.chick.codec import CarrierCodecError, decode_bytes
from chicktools.chick.media import audio_to_wav, images_to_mp4


def tone(seconds=0.125, channels=1, rate=16000):
    samples = np.arange(round(seconds * rate)) / rate
    waveform = np.stack([0.4 * np.sin(2 * np.pi * (440 + channel * 220) * samples)
                         for channel in range(channels)])
    return {"waveform": torch.from_numpy(waveform[None].astype(np.float32)), "sample_rate": rate}


def frames(count=8, height=16, width=16):
    batch = torch.zeros((count, height, width, 3))
    for index in range(count):
        batch[index, :, :, index % 3] = 1
    return batch


def encode_node(**inputs):
    options = dict(password="", title="", fps=8, compress=6, combine_video=True)
    options.update(inputs)
    return plugin.NODE_CLASS_MAPPINGS["ChickHideNode"]().encode(**options)[0]


def extract(carrier, password=""):
    # Exercise the same float -> PNG quantization used by a ComfyUI save node.
    pixels = np.rint(carrier.detach().cpu().numpy() * 255).astype(np.uint8)
    png = BytesIO()
    Image.fromarray(pixels).save(png, format="PNG")
    with Image.open(BytesIO(png.getvalue())) as image:
        return decode_bytes(image, password)


class MediaTests(unittest.TestCase):
    def test_wav_mono_stereo_and_sample_values(self):
        for channels in (1, 2):
            with self.subTest(channels=channels):
                source = tone(channels=channels)
                raw = audio_to_wav(source)
                with wave.open(BytesIO(raw), "rb") as wav:
                    self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getsampwidth(), wav.getnframes()),
                                     (channels, 16000, 2, 2000))
                    pcm = np.frombuffer(wav.readframes(2000), dtype="<i2").reshape(-1, channels) / 32768.0
                np.testing.assert_allclose(pcm, source["waveform"][0].T.numpy(), atol=1 / 32768)

    def test_wav_clipping_and_trailing_silence_preserved(self):
        source = {"waveform": np.array([[[-2, -1, 0.5, 1, 2, 0, 0]]]), "sample_rate": 8000}
        raw, ext = extract(encode_node(audio=source, password="p")[0], "p")
        self.assertEqual(ext, "wav")
        with wave.open(BytesIO(raw)) as wav:
            self.assertEqual(wav.getnframes(), 7)
            self.assertEqual(np.frombuffer(wav.readframes(7), dtype="<i2").tolist(),
                             [-32768, -32768, 16384, 32767, 32767, 0, 0])

    def test_video_frame_count_timing_order_and_no_audio(self):
        raw, ext = extract(encode_node(images=frames())[0])
        self.assertEqual(ext, "mp4")
        with av.open(BytesIO(raw)) as video:
            self.assertEqual(len(video.streams.audio), 0)
            stream = video.streams.video[0]
            self.assertEqual((stream.codec_context.name, stream.width, stream.height, stream.average_rate),
                             ("h264", 16, 16, 8))
            decoded = list(video.decode(video=0))
            self.assertEqual(len(decoded), 8)
            for index, frame in enumerate(decoded):
                self.assertAlmostEqual(float(frame.pts * frame.time_base), index / 8)
                pixel = frame.to_ndarray(format="rgb24")[8, 8]
                expected = np.eye(3, dtype=np.uint8)[index % 3] * 255
                np.testing.assert_allclose(pixel, expected, atol=8)

    def test_mux_audio_loop_and_trim_to_video_duration(self):
        for seconds in (0.125, 2.0):
            with self.subTest(seconds=seconds):
                raw, ext = extract(encode_node(images=frames(), audio=tone(seconds, 2), password="mux")[0], "mux")
                self.assertEqual(ext, "mp4")
                with av.open(BytesIO(raw)) as video:
                    self.assertEqual(len(list(video.decode(video=0))), 8)
                with av.open(BytesIO(raw)) as video:
                    stream = video.streams.audio[0]
                    self.assertEqual(stream.codec_context.name, "aac")
                    self.assertEqual((stream.sample_rate, len(stream.layout.channels)), (16000, 2))
                    self.assertAlmostEqual(float(stream.duration * stream.time_base), 1.0, delta=0.07)
                    samples = np.concatenate([frame.to_ndarray() for frame in video.decode(audio=0)], axis=1)
                    self.assertGreaterEqual(samples.shape[1], 16000)
                    self.assertLessEqual(samples.shape[1], 16000 + 1024)
                    # Sound at the end proves short audio was looped, not dropped or padded with silence.
                    self.assertGreater(float(np.sqrt(np.mean(samples[:, 12000:15000] ** 2))), 0.1)

    def test_odd_dimensions_are_padded_without_resizing(self):
        raw = images_to_mp4(frames(2, 15, 17), 8)
        with av.open(BytesIO(raw)) as video:
            stream = video.streams.video[0]
            self.assertEqual((stream.width, stream.height), (18, 16))
            self.assertEqual(len(list(video.decode(video=0))), 2)

    def test_single_frame_with_audio_and_tiny_image(self):
        raw, ext = extract(encode_node(images=frames(1, 1, 1), audio=tone(), fps=2)[0])
        self.assertEqual(ext, "mp4")
        with av.open(BytesIO(raw)) as video:
            self.assertEqual(len(video.streams.audio), 1)
            decoded = list(video.decode(video=0))
            self.assertEqual(len(decoded), 1)
            self.assertEqual((decoded[0].width, decoded[0].height), (2, 2))

    def test_independent_images(self):
        carriers = encode_node(images=frames(3, 1, 1), combine_video=False)
        self.assertEqual(carriers.shape[0], 3)
        for index, carrier in enumerate(carriers):
            raw, ext = extract(carrier)
            self.assertEqual(ext, "png")
            with Image.open(BytesIO(raw)) as image:
                self.assertEqual(image.size, (1, 1))
                self.assertEqual(image.getpixel((0, 0)), tuple(np.eye(3, dtype=np.uint8)[index] * 255))

    def test_invalid_media_and_ambiguous_inputs_fail_explicitly(self):
        bad_audio = [None, {}, {"waveform": np.zeros((2, 1, 4)), "sample_rate": 8000},
                     {"waveform": np.zeros((1, 3, 4)), "sample_rate": 8000},
                     {"waveform": np.zeros((1, 1, 0)), "sample_rate": 8000},
                     {"waveform": np.array([[[float('nan')]]]), "sample_rate": 8000},
                     {"waveform": np.zeros((1, 1, 4)), "sample_rate": 0}]
        for audio in bad_audio:
            with self.subTest(audio_type=type(audio)), self.assertRaises(CarrierCodecError):
                audio_to_wav(audio)
        for options in ({}, {"images": frames(), "audio": tone(), "combine_video": False},
                        {"images": torch.empty((0, 16, 16, 3))},
                        {"images": torch.full((1, 1, 1, 3), float('nan'))}):
            with self.subTest(keys=list(options)), self.assertRaisesRegex(RuntimeError, r"^\[CHICK_HIDE_ERROR\]"):
                encode_node(**options)
        for fps in (0, 1.5, True, 61):
            with self.subTest(fps=fps), self.assertRaisesRegex(RuntimeError, "fps"):
                encode_node(images=frames(2), fps=fps)

    def test_encoder_failure_timeout_and_missing_output_clean_temp_files(self):
        for mode in ("failure", "timeout", "empty"):
            directories = []
            def run(command, **kwargs):
                root = Path(command[-1]).parent
                directories.append(root)
                self.assertTrue((root / "frames.rgb").exists())
                self.assertTrue((root / "audio.wav").exists())
                if mode == "timeout":
                    raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                return subprocess.CompletedProcess(command, 1 if mode == "failure" else 0, stderr=b"fixture failure")
            with self.subTest(mode=mode), patch("chicktools.chick.media.ffmpeg_executable", return_value="fixture"), \
                    patch("chicktools.chick.media.subprocess.run", side_effect=run) as runner:
                with self.assertRaisesRegex(RuntimeError, r"^\[CHICK_HIDE_ERROR\]"):
                    encode_node(images=frames(2), audio=tone())
                self.assertEqual(runner.call_count, 1)
            self.assertTrue(directories)
            self.assertTrue(all(not root.exists() for root in directories))
