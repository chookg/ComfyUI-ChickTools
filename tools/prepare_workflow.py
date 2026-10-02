"""Inspect a ComfyUI schema and prepare small workflows without executing them."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


NODE_TYPES = ("EmptyImage", "ChickHideNode", "ChickSaveImage", "NotifyMeNode", "PrimitiveStringMultiline")


def inputs_of(node):
    spec = node.get("input", {})
    return {**spec.get("required", {}), **spec.get("optional", {})}


def output_slots(node):
    types = node.get("output", [])
    names = node.get("output_name", [])
    lists = node.get("output_is_list", [])
    return [{"slot": i, "type": kind, "name": names[i] if i < len(names) else kind,
             "is_list": bool(lists[i]) if i < len(lists) else False}
            for i, kind in enumerate(types)]


def image_slot(node):
    slots = [out["slot"] for out in output_slots(node) if out["type"] == "IMAGE" and not out["is_list"]]
    return slots[0] if len(slots) == 1 else None


def analyze(info):
    if not isinstance(info, dict):
        raise ValueError("object_info must be a JSON object")
    for name in NODE_TYPES:
        if name in info and not isinstance(info[name], dict):
            raise ValueError("node schemas must be JSON objects")
    nodes = {name: info.get(name, {}) for name in NODE_TYPES}
    blockers = []
    expected = {
        "EmptyImage": {"width": "INT", "height": "INT", "batch_size": "INT", "color": "INT"},
        "ChickHideNode": {"password": "STRING", "title": "STRING", "fps": "INT",
                          "compress": [2, 6, 8], "combine_video": "BOOLEAN", "images": "IMAGE"},
        "ChickSaveImage": {"images": "IMAGE", "filename_prefix": "STRING"},
    }
    for name, required in expected.items():
        if name not in info:
            blockers.append(f"missing node: {name}")
            continue
        spec = nodes[name]
        if spec.get("is_input_list", False):
            blockers.append(f"list input contract requires review: {name}")
        declared = inputs_of(spec)
        for key, kind in required.items():
            value = declared.get(key)
            if not isinstance(value, (list, tuple)) or not value or value[0] != kind:
                blockers.append(f"unexpected input contract: {name}.{key}")
        supplied = set(required)
        extra = set(spec.get("input", {}).get("required", {})) - supplied
        if extra:
            blockers.append(f"additional required inputs: {name}: {', '.join(sorted(extra))}")
    for name in ("EmptyImage", "ChickHideNode"):
        if name in info and image_slot(nodes[name]) is None:
            blockers.append(f"expected one scalar IMAGE output: {name}")
    if "ChickSaveImage" in info and not nodes["ChickSaveImage"].get("output_node", False):
        blockers.append("ChickSaveImage must be an output node")
    callback_blockers = []
    notify = nodes["NotifyMeNode"]
    if "NotifyMeNode" not in info:
        callback_blockers.append("missing node: NotifyMeNode")
    else:
        spec = notify.get("input", {})
        for group, key, kind in (("required", "callback_url", "STRING"),
                                 ("optional", "id", "STRING"),
                                 ("optional", "msg", "STRING"),
                                 ("optional", "passthrough", "*")):
            field = spec.get(group, {}).get(key)
            if not isinstance(field, (list, tuple)) or not field or field[0] != kind:
                callback_blockers.append(f"unexpected input contract: NotifyMeNode.{key}")
        if set(spec.get("required", {})) != {"callback_url"}:
            callback_blockers.append("NotifyMeNode must require only callback_url")
        if notify.get("is_input_list", False):
            callback_blockers.append("NotifyMeNode must accept scalar inputs")
        if (notify.get("output") != ["*"] or notify.get("output_name") != ["passthrough"]):
            callback_blockers.append("NotifyMeNode must expose one wildcard passthrough output")
        if not notify.get("output_node", False):
            callback_blockers.append("NotifyMeNode must remain an output node")
    text_blockers = list(callback_blockers)
    source = nodes["PrimitiveStringMultiline"]
    text_slot = None
    if "PrimitiveStringMultiline" not in info:
        text_blockers.append("missing example text source: PrimitiveStringMultiline")
    else:
        value = inputs_of(source).get("value")
        if not isinstance(value, (list, tuple)) or not value or value[0] != "STRING":
            text_blockers.append("unexpected input contract: PrimitiveStringMultiline.value")
        if set(source.get("input", {}).get("required", {})) - {"value"} or source.get("is_input_list", False):
            text_blockers.append("unsupported example text source inputs")
        slots = [out["slot"] for out in output_slots(source) if out["type"] == "STRING" and not out["is_list"]]
        if len(slots) == 1:
            text_slot = slots[0]
        else:
            text_blockers.append("example text source must expose one scalar STRING output")
    return {
        "nodes": {name: {"registered": name in info, "outputs": output_slots(nodes[name])} for name in NODE_TYPES},
        "carrier_workflow_ready": not blockers,
        "carrier_blockers": blockers,
        "callback_wiring_ready": not callback_blockers,
        "callback_blockers": callback_blockers,
        "text_callback_workflow_ready": not text_blockers,
        "text_callback_blockers": text_blockers,
        "text_output_slot": text_slot,
        "execution_submitted": False,
        "next_checks": ["Fill callback_url and set your task id before running a notification workflow.",
                        "Check that the receiver gets exactly the connected text in msg, or an empty string without a connection.",
                        "Download the saved carrier PNG and verify its payload and metadata."]}


def build_prompts(info, report):
    results = {}
    if report["carrier_workflow_ready"]:
        results["carrier-smoke"] = {
            "1": {"class_type": "EmptyImage", "inputs": {"width": 16, "height": 16, "batch_size": 1, "color": 255}},
            "2": {"class_type": "ChickHideNode", "inputs": {
                "images": ["1", image_slot(info["EmptyImage"])], "password": "", "title": "Smoke",
                "fps": 16, "compress": 2, "combine_video": True}},
            "3": {"class_type": "ChickSaveImage", "inputs": {
                "images": ["2", image_slot(info["ChickHideNode"])], "filename_prefix": "ChickTools/smoke"}},
        }
    if report["callback_wiring_ready"]:
        results["notify-empty-smoke"] = {
            "1": {"class_type": "NotifyMeNode", "inputs": {"callback_url": "", "id": "demo-task-001"}},
        }
    if report["text_callback_workflow_ready"]:
        results["notify-text-smoke"] = {
            "1": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "Sample message"}},
            "2": {"class_type": "NotifyMeNode", "inputs": {
                "callback_url": "", "id": "demo-task-001", "msg": ["1", report["text_output_slot"]],
                "passthrough": ["1", report["text_output_slot"]]}},
        }
    return results


def build_canvas(prompt, info):
    """Render the minimal prompt as a canvas without copying schema defaults or secrets."""
    widget_order = {"EmptyImage": ["width", "height", "batch_size", "color"],
                    "LoadImage": ["image"], "ChickRestoreImage": ["password"],
                    "ImageBatchTestPattern": ["batch_size", "start_from", "text_x", "text_y",
                                               "width", "height", "font", "font_size"],
                    "ChickHideNode": ["password", "title", "fps", "compress", "combine_video"],
                    "ChickSaveImage": ["filename_prefix"], "NotifyMeNode": ["callback_url", "allow_localhost", "id"],
                    "PrimitiveStringMultiline": ["value"]}
    nodes, links = {}, []
    for order, (id, data) in enumerate(prompt.items()):
        kind, inputs = data["class_type"], data["inputs"]
        names = [name for name in widget_order[kind] if name in inputs_of(info[kind])]
        ports = []
        for key, field in inputs_of(info[kind]).items():
            if key not in names or isinstance(inputs.get(key), list):
                port = {"name": key, "type": field[0], "link": None}
                if key in names:
                    port["widget"] = {"name": key}
                ports.append(port)
        nodes[id] = {"id": int(id), "type": kind, "pos": [60 + order * 330, 140], "size": [300, 240],
                     "flags": {}, "order": order, "mode": 0, "inputs": ports,
                     "outputs": [{"name": out["name"], "type": out["type"], "slot_index": out["slot"], "links": []}
                                 for out in output_slots(info[kind])],
                     "properties": {"Node name for S&R": kind},
                     "widgets_values": [inputs.get(key, False if key == "allow_localhost" else "")
                                        if not isinstance(inputs.get(key), list) else "" for key in names]}
    for id, data in prompt.items():
        for input_index, port in enumerate(nodes[id]["inputs"]):
            value = data["inputs"].get(port["name"])
            if not isinstance(value, list):
                continue
            source, slot = value
            link_id = len(links) + 1
            source_type = nodes[source]["outputs"][slot]["type"]
            links.append([link_id, int(source), slot, int(id), input_index, source_type])
            port["link"] = link_id
            nodes[source]["outputs"][slot]["links"].append(link_id)
    return {"last_node_id": max(node["id"] for node in nodes.values()), "last_link_id": len(links),
            "nodes": list(nodes.values()), "links": links, "groups": [], "config": {},
            "extra": {"ds": {"scale": 0.7, "offset": [0, 0]}}, "version": 0.4}


def read_info(base_url):
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("base URL must be HTTP(S) without credentials, query or fragment")
    # Read-only: this tool never posts to /prompt or calls a callback endpoint.
    with urlopen(base_url.rstrip("/") + "/object_info", timeout=15) as response:
        return json.load(response)


def write_preparation(info, output):
    report = analyze(info)
    output.mkdir(parents=True, exist_ok=True)
    prompts = build_prompts(info, report)
    for name, prompt in prompts.items():
        for suffix, value in (("api", prompt), ("canvas", build_canvas(prompt, info))):
            with (output / f"{name}.{suffix}.json").open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
    with (output / "report.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--base-url", help="ComfyUI API base URL")
    source.add_argument("--object-info", type=Path, help="Saved /object_info response")
    parser.add_argument("--out-dir", type=Path, required=True, help="New output directory for this environment")
    args = parser.parse_args()
    if args.out_dir.exists():
        parser.error("choose a new output directory so old workflows cannot be mistaken for fresh results")
    try:
        info = json.loads(args.object_info.read_text(encoding="utf-8")) if args.object_info else read_info(args.base_url)
        report = write_preparation(info, args.out_dir)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"Preparation failed ({type(exc).__name__}); check the schema or connection.\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["carrier_workflow_ready"] and report["callback_wiring_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
