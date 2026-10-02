"""Build the small model-free video and callback demonstration workflow."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_workflow import build_canvas, read_info  # noqa: E402


def main() -> None:
    info = read_info("http://127.0.0.1:8188")
    prompt = {
        "1": {"class_type": "ImageBatchTestPattern", "inputs": {
            "batch_size": 8, "start_from": 0, "text_x": 5, "text_y": 5,
            "width": 64, "height": 64, "font": "FreeMono.ttf", "font_size": 12}},
        "2": {"class_type": "ChickHideNode", "inputs": {
            "password": "demo-password", "title": "ChickTools video demo", "fps": 8,
            "compress": 2, "combine_video": True, "images": ["1", 0]}},
        "3": {"class_type": "ChickSaveImage", "inputs": {
            "filename_prefix": "ChickTools/video-demo", "images": ["2", 0]}},
        "4": {"class_type": "PrimitiveStringMultiline", "inputs": {
            "value": "视频载体测试已完成\n这条文本由 NotifyMe 发送到本地结果页。"}},
        "5": {"class_type": "NotifyMeNode", "inputs": {
            "callback_url": "http://127.0.0.1:8765/callback",
            "id": "demo-task-001",
            "allow_localhost": True, "msg": ["4", 0]}},
    }
    workflow = build_canvas(prompt, info)
    layout = {
        1: ([70, 90], [330, 300], "视频测试图 · 8 帧 · 64×64"),
        2: ([460, 90], [320, 240], "小鸡节点 | Chick Hide · MP4"),
        3: ([850, 90], [340, 350], "小鸡载体保存 | Chick Private Save"),
        4: ([70, 520], [560, 180], "输入通知文本 · STRING"),
        5: ([850, 520], [340, 200], "通知我 | Notify Me"),
    }
    for node in workflow["nodes"]:
        node["pos"], node["size"], node["title"] = layout[node["id"]]
    workflow["groups"] = [
        {"id": 1, "title": "① 8 帧测试图 → 小鸡节点 → MP4 载体",
         "bounding": [40, 20, 1190, 440], "color": "#3b7184", "font_size": 24, "flags": {}},
        {"id": 2, "title": "② 文本 → NotifyMe → 本地结果页",
         "bounding": [40, 450, 1190, 300], "color": "#596c95", "font_size": 24, "flags": {}},
    ]
    workflow["extra"]["ds"] = {"scale": 0.72, "offset": [0, 0]}
    destination = ROOT / "examples" / "chick_notify_video_example.json"
    destination.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    print(destination)


if __name__ == "__main__":
    main()
