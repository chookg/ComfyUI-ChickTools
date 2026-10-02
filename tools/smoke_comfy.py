"""Model-free ComfyUI integration test with a loopback HTTP receiver.

Run with ComfyUI's Python:
python tools/smoke_comfy.py --comfy /path/to/ComfyUI
"""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import threading
import time
import wave
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import av
import numpy as np
from PIL import Image

# Embedded ComfyUI Python can run in isolated mode and omit the script folder
# from sys.path. Keep this helper importable in both regular and embedded runs.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_workflow import write_preparation, build_prompts

ROOT = Path(__file__).resolve().parents[1]
MESSAGE = '  通知消息 🐥\n保留换行与空格  '


def get_json(url, payload=None):
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def child(args):
    comfy = args.comfy.resolve()
    sys.path.insert(0, str(comfy))
    os.chdir(comfy)
    sys.argv = [str(comfy / "main.py"), "--cpu", "--listen", "127.0.0.1",
                "--port", str(args.port), "--disable-auto-launch", "--disable-api-nodes",
                "--disable-all-custom-nodes", "--whitelist-custom-nodes", "ComfyUI-ChickTools",
                "--user-directory", str(args.workspace / "user"),
                "--input-directory", str(args.workspace / "input"),
                "--output-directory", str(args.workspace / "output"),
                "--temp-directory", str(args.workspace / "temp"),
                "--database-url", "sqlite:///:memory:"]
    import comfy.options
    comfy.options.enable_args_parsing()
    runpy.run_path(str(args.comfy.resolve() / "main.py"), run_name="__main__")


def main(args):
    sys.path.insert(0, str(ROOT))
    from chick.codec import CarrierCodecError, decode_bytes
    args.workspace.mkdir(parents=True, exist_ok=True)
    (args.workspace / "user").mkdir(exist_ok=True)
    (args.workspace / "input").mkdir(exist_ok=True)
    samples = np.arange(2000) / 16000
    pcm = np.rint(np.sin(2 * np.pi * 440 * samples) * 12000).astype("<i2")
    with wave.open(str(args.workspace / "input" / "tone.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm.tobytes())
    callbacks = []
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_POST(self):
            callbacks.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    callback_url = f"http://127.0.0.1:{server.server_port}/callback"
    command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
               "--comfy", str(args.comfy.resolve()), "--workspace", str(args.workspace.resolve()),
               "--port", str(args.port), "--server-child"]
    base = f"http://127.0.0.1:{args.port}"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    try:
        with (args.workspace / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                deadline = time.monotonic() + 120
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("ComfyUI exited; see .local/smoke/server.log")
                    try:
                        stats = get_json(base + "/system_stats")
                        break
                    except (OSError, TimeoutError):
                        if time.monotonic() > deadline:
                            raise TimeoutError("ComfyUI startup timed out")
                        time.sleep(0.5)
                assert stats["devices"][0]["type"] == "cpu", stats
                info = get_json(base + "/object_info")
                assert all(name in info for name in ("ChickHideNode", "NotifyMeNode", "ChickSaveImage"))
                saver_type = "ChickSaveImage"
                preparation = write_preparation(info, args.workspace / "preparation")
                assert preparation["carrier_workflow_ready"], preparation
                assert preparation["text_callback_workflow_ready"], preparation
                assert "text_input" not in info["ChickHideNode"]["input"].get("optional", {})
                assert info["NotifyMeNode"]["output"] == ["*"]
                assert info["NotifyMeNode"]["output_name"] == ["passthrough"]
                prompt = {
                    "1": {"class_type": "EmptyImage", "inputs": {"width": 8, "height": 8, "batch_size": 1, "color": 255}},
                    "2": {"class_type": "ChickHideNode", "inputs": {"images": ["1", 0], "password": "", "title": "smoke", "fps": 24, "compress": 2, "combine_video": False}},
                    "4": {"class_type": saver_type, "inputs": {"images": ["2", 0], "filename_prefix": "ChickTools/smoke"}}
                }
                cases = [("image", copy.deepcopy(prompt), "png", 1, False),
                         ("image_repeat", copy.deepcopy(prompt), "png", 1, False)]
                for with_audio in (False, True):
                    video = copy.deepcopy(prompt)
                    video["1"]["inputs"].update(width=16, height=16, batch_size=8)
                    video["2"]["inputs"].update(combine_video=True, fps=8, password="fixture-video-password", compress=6)
                    if with_audio:
                        video["5"] = {"class_type": "LoadAudio", "inputs": {"audio": "tone.wav"}}
                        video["2"]["inputs"]["audio"] = ["5", 0]
                    cases.append(("video_audio" if with_audio else "video", video, "mp4", 8, with_audio))
                audio_only = copy.deepcopy(prompt)
                del audio_only["1"]
                del audio_only["2"]["inputs"]["images"]
                audio_only["5"] = {"class_type": "LoadAudio", "inputs": {"audio": "tone.wav"}}
                audio_only["2"]["inputs"].update(audio=["5", 0], compress=8)
                cases.append(("audio", audio_only, "wav", 1, True))
                batch = copy.deepcopy(prompt)
                batch["1"]["inputs"]["batch_size"] = 2
                cases.append(("image_batch", batch, "png", 2, False))
                saved = build_prompts(info, preparation)["carrier-smoke"]
                saved["2"]["inputs"]["password"] = "fixture-image-password-小鸡"
                cases.append(("saved_image", saved, "png", 1, False))
                cases.append(("saved_image_repeat", copy.deepcopy(saved), "png", 1, False))
                runs = []
                for name, workflow, extension, frame_count, with_audio in cases:
                    provenance = {"Label": "1", "ContentProducer": "synthetic-fixture"}
                    metadata = {"workflow": {"nodes": [{"id": 2, "type": "ChickHideNode",
                        "widgets_values": [workflow["2"]["inputs"]["password"]]}]},
                        "private_debug": workflow, "AIGC": provenance}
                    submitted = get_json(base + "/prompt", {"prompt": workflow, "client_id": "chicktools-smoke",
                                                            "extra_data": {"extra_pnginfo": metadata}})
                    prompt_id = submitted["prompt_id"]
                    deadline = time.monotonic() + 20
                    while True:
                        history = get_json(base + "/history/" + prompt_id)
                        if prompt_id in history:
                            result = history[prompt_id]
                            assert result["status"]["status_str"] == "success", result
                            assert result["status"]["completed"], result
                            outputs = result["outputs"]["3" if name.startswith("saved_image") else "4"]["images"]
                            assert len(outputs) == (frame_count if extension == "png" else 1)
                            for output in outputs:
                                with urlopen(base + "/view?" + urlencode(output), timeout=3) as preview:
                                    png_bytes = preview.read()
                                with Image.open(BytesIO(png_bytes)) as stored:
                                    assert set(stored.info) == {"AIGC"}, stored.info.keys()
                                    assert json.loads(stored.info["AIGC"]) == provenance
                                    image = stored.convert("RGB")
                                password = workflow["2"]["inputs"]["password"]
                                if password:
                                    assert password.encode("utf-8") not in png_bytes
                                    for invalid in ("", "fixture-wrong-password"):
                                        try:
                                            decode_bytes(image, invalid)
                                        except CarrierCodecError:
                                            pass
                                        else:
                                            raise AssertionError("Protected carrier decoded with an invalid password")
                                raw, ext = decode_bytes(image, password)
                                assert image.size == (640, 640) and ext == extension
                                if ext == "png":
                                    with Image.open(BytesIO(raw)) as restored:
                                        side = 16 if name.startswith("saved_image") else 8
                                        assert restored.size == (side, side) and restored.getpixel((0, 0)) == (0, 0, 255)
                                elif ext == "wav":
                                    with wave.open(BytesIO(raw)) as restored:
                                        assert restored.getframerate() == 16000 and restored.getnframes() == 2000
                                        assert restored.readframes(2000) == pcm.tobytes()
                                else:
                                    with av.open(BytesIO(raw)) as restored:
                                        assert len(restored.streams.audio) == int(with_audio)
                                        stream = restored.streams.video[0]
                                        assert stream.average_rate == 8 and (stream.width, stream.height) == (16, 16)
                                        decoded = list(restored.decode(video=0))
                                        assert len(decoded) == 8
                                        np.testing.assert_allclose(decoded[-1].to_ndarray(format="rgb24")[8, 8], [0, 0, 255], atol=8)
                                    if with_audio:
                                        with av.open(BytesIO(raw)) as restored:
                                            track = np.concatenate([f.to_ndarray() for f in restored.decode(audio=0)], axis=1)
                                            assert track.shape[1] >= 16000 and np.max(np.abs(track[:, 12000:15000])) > 0.1
                            runs.append({"case": name, "prompt_id": prompt_id, "status": "success",
                                         "payload_extension": extension, "preview_count": len(outputs),
                                         "workflow_metadata_absent": True, "aigc_preserved": True,
                                         "password_checks_passed": bool(password)})
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError("Tiny workflow timed out")
                        time.sleep(0.1)
                assert callbacks == [], callbacks
                prepared = build_prompts(info, preparation)
                text_prompt = copy.deepcopy(prepared["notify-text-smoke"])
                text_prompt["1"]["inputs"]["value"] = MESSAGE
                text_prompt["2"]["inputs"].update(callback_url=callback_url, allow_localhost=True, id="000123-任务🐥")
                empty_prompt = copy.deepcopy(prepared["notify-empty-smoke"])
                empty_prompt["1"]["inputs"].update(callback_url=callback_url, allow_localhost=True)
                empty_prompt["1"]["inputs"].pop("id")  # Existing workflows omit the new field.
                whitespace_prompt = copy.deepcopy(text_prompt)
                whitespace_prompt["1"]["inputs"]["value"] = "  \n\t"
                whitespace_prompt["2"]["inputs"]["id"] = "000124"
                notification_cases = [("notify_text", text_prompt, MESSAGE, "000123-任务🐥"),
                                      ("notify_text_repeat", copy.deepcopy(text_prompt), MESSAGE, "000123-任务🐥"),
                                      ("notify_unconnected", empty_prompt, "", ""),
                                      ("notify_whitespace", whitespace_prompt, "  \n\t", "000124")]
                for name, workflow, expected, task_id in notification_cases:
                    before = len(callbacks)
                    submitted = get_json(base + "/prompt", {"prompt": workflow, "client_id": "chicktools-smoke"})
                    prompt_id = submitted["prompt_id"]
                    deadline = time.monotonic() + 20
                    while True:
                        history = get_json(base + "/history/" + prompt_id)
                        if prompt_id in history:
                            result = history[prompt_id]
                            assert result["status"]["status_str"] == "success", result
                            assert result["status"]["completed"], result
                            assert callbacks[before:] == [{"id": task_id, "msg": expected}], callbacks
                            runs.append({"case": name, "prompt_id": prompt_id, "status": "success",
                                         "message_exact": True, "id_exact": True, "callback_count": 1})
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError("Tiny notification workflow timed out")
                        time.sleep(0.1)
                assert callbacks == [{"id": item[3], "msg": item[2]} for item in notification_cases], callbacks
                report = {"device": "cpu", "models_loaded": 0, "image_shape": [1, 640, 640, 3],
                          "registered_nodes": ["ChickHideNode", saver_type, "NotifyMeNode"],
                          "callback_count": len(callbacks), "runs": runs,
                          "fixture": "real loopback HTTP with allow_localhost enabled; no validation replacement"}
                (args.workspace / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False, indent=2))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=ROOT / ".local" / "smoke")
    parser.add_argument("--port", type=int, default=8191)
    parser.add_argument("--server-child", action="store_true")
    args = parser.parse_args()
    if args.server_child:
        child(args)
    else:
        main(args)
