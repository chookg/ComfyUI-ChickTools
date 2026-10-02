"""CPU media serialization. All temporary files belong to one invocation."""

from io import BytesIO
from numbers import Integral
from pathlib import Path
import subprocess
import tempfile
import wave

import numpy as np

from .codec import CarrierCodecError, image_pixels


def image_batch(images):
    """Validate batch geometry without copying all frames to the CPU at once."""
    if not hasattr(images, "shape"):
        images = np.asarray(images)
    if len(images.shape) == 3:
        images = images[None, ...]
    if (len(images.shape) != 4 or any(size < 1 for size in images.shape)
            or images.shape[-1] not in (3, 4)):
        raise CarrierCodecError("images must have shape NxHxWx3 or NxHxWx4 with non-empty dimensions")
    return images


def audio_to_wav(audio) -> bytes:
    """Serialize standard ComfyUI AUDIO (1, channels, samples) as PCM16 WAV."""
    if not isinstance(audio, dict) or "waveform" not in audio or "sample_rate" not in audio:
        raise CarrierCodecError("audio requires waveform and sample_rate")
    rate = audio["sample_rate"]
    if isinstance(rate, bool) or not isinstance(rate, Integral) or not 8000 <= rate <= 192000:
        raise CarrierCodecError("sample_rate must be an integer between 8000 and 192000")
    waveform = audio["waveform"]
    if hasattr(waveform, "detach"):
        waveform = waveform.detach().cpu().float().numpy()
    samples = np.asarray(waveform)
    if samples.ndim != 3 or samples.shape[0] != 1 or samples.shape[1] not in (1, 2) or samples.shape[2] < 1:
        raise CarrierCodecError("audio waveform must have shape 1x1xN or 1x2xN")
    if samples.dtype.kind not in "fiu" or not np.isfinite(samples).all():
        raise CarrierCodecError("audio samples must be finite numbers")
    pcm = np.rint(np.clip(samples[0].T, -1.0, 1.0) * 32768.0)
    pcm = np.clip(pcm, -32768, 32767).astype("<i2")
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(samples.shape[1])
        wav.setsampwidth(2)
        wav.setframerate(int(rate))
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


def ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise CarrierCodecError("install imageio-ffmpeg or set IMAGEIO_FFMPEG_EXE to an FFmpeg executable") from exc


def images_to_mp4(images, fps: int, audio=None) -> bytes:
    """Encode H.264/AAC MP4; loop or trim audio to the exact frame duration."""
    frames = image_batch(images)
    if isinstance(fps, bool) or not isinstance(fps, Integral) or not 1 <= fps <= 60:
        raise CarrierCodecError("fps must be an integer between 1 and 60")
    audio_bytes = audio_to_wav(audio) if audio is not None else None
    executable = ffmpeg_executable()
    count, height, width, _ = frames.shape
    with tempfile.TemporaryDirectory(prefix="chicktools-media-") as directory:
        root = Path(directory)
        raw_path, output_path = root / "frames.rgb", root / "media.mp4"
        # Only one converted frame is resident in addition to the caller's IMAGE batch.
        with raw_path.open("wb") as raw:
            for frame in frames:
                raw.write(np.ascontiguousarray(image_pixels(frame)[..., :3]).tobytes())
        command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-filter_threads", "1", "-f", "rawvideo", "-pixel_format", "rgb24",
                   "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", str(raw_path)]
        if audio_bytes is not None:
            audio_path = root / "audio.wav"
            audio_path.write_bytes(audio_bytes)
            command += ["-stream_loop", "-1", "-i", str(audio_path)]
        command += ["-map", "0:v:0", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-c:v", "libx264", "-threads", "2", "-preset", "medium", "-crf", "16",
                    "-pix_fmt", "yuv420p"]
        if audio_bytes is not None:
            command += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-threads:a", "1"]
        else:
            command += ["-an"]
        command += ["-t", f"{count / fps:.9f}", "-movflags", "+faststart", str(output_path)]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, timeout=300, check=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise CarrierCodecError("video encoding exceeded 300 seconds") from exc
        except OSError as exc:
            raise CarrierCodecError("FFmpeg could not be started") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace")[-1500:].strip()
            raise CarrierCodecError(f"FFmpeg encoding failed ({result.returncode}): {detail}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise CarrierCodecError("FFmpeg produced no video")
        return output_path.read_bytes()
