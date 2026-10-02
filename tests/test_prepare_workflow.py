import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

from plugin_loader import plugin, ROOT

spec = importlib.util.spec_from_file_location("prepare_workflow", ROOT / "tools/prepare_workflow.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def schema(save_outputs=None, save_names=None):
    result = {}
    for name, cls in plugin.NODE_CLASS_MAPPINGS.items():
        result[name] = {"input": cls.INPUT_TYPES(), "output": list(cls.RETURN_TYPES),
                        "output_name": list(cls.RETURN_NAMES), "output_node": getattr(cls, "OUTPUT_NODE", False)}
    result["EmptyImage"] = {"input": {"required": {key: ["INT"] for key in ("width", "height", "batch_size", "color")}},
                            "output": ["IMAGE"], "output_name": ["IMAGE"]}
    result["ChickSaveImage"] = {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {"default": "private-default"}]}},
                           "output": save_outputs or [], "output_name": save_names or [], "output_node": True}
    result["PrimitiveStringMultiline"] = {"input": {"required": {"value": ["STRING", {"default": "private-default"}]}},
                                         "output": ["STRING"], "output_name": ["STRING"]}
    return result


class PreparationTests(unittest.TestCase):
    def test_notifications_do_not_depend_on_save_outputs(self):
        for types, names in (([], []), (["IMAGE"], ["images"]), (["STRING"], ["filename"])):
            info = schema(types, names)
            report = prepare.analyze(info)
            self.assertTrue(report["carrier_workflow_ready"])
            self.assertTrue(report["callback_wiring_ready"])
            prompts = prepare.build_prompts(info, report)
            self.assertEqual(set(prompts), {"carrier-smoke", "notify-empty-smoke", "notify-text-smoke"})
            self.assertEqual(prompts["carrier-smoke"]["3"]["class_type"], "ChickSaveImage")
            self.assertEqual(prompts["notify-empty-smoke"]["1"]["inputs"], {"callback_url": "", "id": "demo-task-001"})

    def test_text_source_slots_and_canvas_preserve_wiring(self):
        for types, names, text_slot in ((["STRING"], ["STRING"], 0),
                                      (["INT", "STRING"], ["length", "text"], 1)):
            info = schema()
            info["PrimitiveStringMultiline"].update(output=types, output_name=names)
            report = prepare.analyze(info)
            prompt = prepare.build_prompts(info, report)["notify-text-smoke"]
            self.assertEqual(prompt["2"]["inputs"], {
                "callback_url": "", "id": "demo-task-001", "msg": ["1", text_slot], "passthrough": ["1", text_slot]})
            canvas = prepare.build_canvas(prompt, info)
            nodes = {node["id"]: node for node in canvas["nodes"]}
            self.assertEqual(nodes[2]["widgets_values"], ["", False, "demo-task-001"])
            for id, source, slot, target, port, kind in canvas["links"]:
                self.assertIn(id, nodes[source]["outputs"][slot]["links"])
                self.assertEqual(nodes[target]["inputs"][port]["link"], id)
                self.assertEqual(nodes[source]["outputs"][slot]["type"], kind)
                self.assertIn(nodes[target]["inputs"][port]["type"], (kind, "*"))
            self.assertEqual(nodes[2]["outputs"], [{"name": "passthrough", "type": "*", "slot_index": 0, "links": []}])
            empty = prepare.build_canvas(prepare.build_prompts(info, report)["notify-empty-smoke"], info)
            self.assertEqual(empty["nodes"][0]["inputs"], [
                {"name": "msg", "type": "STRING", "link": None},
                {"name": "passthrough", "type": "*", "link": None}])
            with tempfile.TemporaryDirectory() as temp:
                prepare.write_preparation(info, Path(temp))
                self.assertEqual(len(list(Path(temp).glob("*.json"))), 7)
                for file in Path(temp).glob("*.json"):
                    self.assertNotIn("private-default", file.read_text())

    def test_missing_media_does_not_block_independent_notifications(self):
        for name in ("ChickHideNode", "ChickSaveImage", "EmptyImage"):
            info = schema()
            del info[name]
            report = prepare.analyze(info)
            self.assertFalse(report["carrier_workflow_ready"])
            self.assertTrue(report["callback_wiring_ready"])
            self.assertEqual(set(prepare.build_prompts(info, report)), {"notify-empty-smoke", "notify-text-smoke"})
        info = schema()
        info["ChickSaveImage"]["input"]["required"]["private_key"] = ["STRING"]
        self.assertFalse(prepare.analyze(info)["carrier_workflow_ready"])

    def test_legacy_or_incompatible_notification_schema_is_blocked(self):
        base = schema()
        bad = []
        missing = copy.deepcopy(base)
        del missing["NotifyMeNode"]
        bad.append(missing)
        for change in ("legacy", "required_msg", "wrong_type", "missing_id", "wrong_id", "missing_passthrough", "wrong_passthrough",
                       "list", "output", "nonterminal"):
            info = copy.deepcopy(base)
            node = info["NotifyMeNode"]
            if change == "legacy":
                node["input"]["required"].update(image=["IMAGE"], preview_url=["STRING"])
            elif change == "required_msg":
                node["input"]["required"]["msg"] = node["input"]["optional"].pop("msg")
            elif change == "wrong_type":
                node["input"]["optional"]["msg"] = ["IMAGE"]
            elif change == "missing_id":
                del node["input"]["optional"]["id"]
            elif change == "wrong_id":
                node["input"]["optional"]["id"] = ["INT"]
            elif change == "missing_passthrough":
                del node["input"]["optional"]["passthrough"]
            elif change == "wrong_passthrough":
                node["input"]["optional"]["passthrough"] = ["IMAGE"]
            elif change == "list":
                node["is_input_list"] = True
            elif change == "output":
                node["output"] = ["IMAGE"]
            else:
                node["output_node"] = False
            bad.append(info)
        for info in bad:
            report = prepare.analyze(info)
            self.assertTrue(report["carrier_workflow_ready"])
            self.assertFalse(report["callback_wiring_ready"])
            self.assertEqual(set(prepare.build_prompts(info, report)), {"carrier-smoke"})

    def test_missing_or_ambiguous_text_source_still_allows_empty_message(self):
        for change in ("missing", "multiple", "list", "extra"):
            info = schema()
            node = info["PrimitiveStringMultiline"]
            if change == "missing":
                del info["PrimitiveStringMultiline"]
            elif change == "multiple":
                node["output"] = ["STRING", "STRING"]
            elif change == "list":
                node["output_is_list"] = [True]
            else:
                node["input"]["required"]["private_key"] = ["STRING"]
            report = prepare.analyze(info)
            self.assertTrue(report["callback_wiring_ready"])
            self.assertFalse(report["text_callback_workflow_ready"])
            self.assertEqual(set(prepare.build_prompts(info, report)), {"carrier-smoke", "notify-empty-smoke"})

    def test_live_probe_only_reads_schema(self):
        requests = []
        info = schema()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                requests.append(("GET", self.path))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(info).encode())
            def do_POST(self):
                requests.append(("POST", self.path))
                self.send_error(405)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            loaded = prepare.read_info(f"http://127.0.0.1:{server.server_port}")
            self.assertTrue(prepare.analyze(loaded)["carrier_workflow_ready"])
            self.assertEqual(requests, [("GET", "/object_info")])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
