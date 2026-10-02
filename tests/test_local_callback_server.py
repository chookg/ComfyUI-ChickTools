import asyncio
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from plugin_loader import plugin, ROOT
from chicktools.chick.codec import encode_bytes

spec = importlib.util.spec_from_file_location("local_callback_server", ROOT / "tools/local_callback_server.py")
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


class LocalReceiverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp.name) / "received.jsonl"
        self.state = receiver.ReceiverState(log_path=self.log_path)
        self.client = TestClient(TestServer(receiver.create_app(self.state)))
        await self.client.start_server()
        self.base = str(self.client.make_url("/")).rstrip("/")

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_node_succeeds_after_text_is_logged_and_published(self):
        node = plugin.NODE_CLASS_MAPPINGS["NotifyMeNode"]()
        message = '中文 🐥\n  <script>message</script>  '
        ws = await self.client.ws_connect("/ws")
        self.addAsyncCleanup(ws.close)
        await ws.receive_json(timeout=2)
        for text in (message, ""):
            payload = object()
            result = await asyncio.to_thread(node.notify, self.base + "/callback", text,
                                             allow_localhost=True, id="000123", passthrough=payload)
            self.assertIs(result[0], payload)
            update = await ws.receive_json(timeout=2)
            self.assertEqual(update["messages"][-1]["msg"], text)
            self.assertEqual(update["messages"][-1]["id"], "000123")
        response = await self.client.get("/events")
        data = await response.json()
        records = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(data["received"], 2)
        self.assertEqual(data["messages"], records)
        self.assertEqual([record["msg"] for record in records], [message, ""])
        self.assertEqual([record["id"] for record in records], ["000123", "000123"])
        self.assertEqual(len({record["event_id"] for record in records}), 2)
        restored = receiver.ReceiverState(log_path=self.log_path)
        self.assertEqual(list(restored.messages), records)
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("NotifyMe", await response.text())

    async def test_invalid_request_is_not_recorded(self):
        for path, body, content_type, status in (
            ("/callback", b'{"msg":123}', "application/json", 200),
            ("/callback", b'{"id":123,"msg":"x"}', "application/json", 200),
            ("/callback", b'{"id":null,"msg":"x"}', "application/json", 200),
            ("/callback", b'invalid', "application/json", 200),
            ("/callback", b'{"msg":"x"}', "text/plain", 200),
            ("/other", b'{"msg":"x"}', "application/json", 404),
        ):
            with self.subTest(path=path, body=body):
                response = await self.client.post(path, data=body, headers={"Content-Type": content_type})
                self.assertEqual(response.status, status)
        self.assertEqual(self.state.received, 0)
        self.assertFalse(self.log_path.exists())

    async def test_legacy_callbacks_and_logs_have_empty_task_id(self):
        old_record = {"id": "legacy-event", "received_at": "2026-01-01", "msg": "old"}
        self.log_path.write_text(json.dumps(old_record) + "\n", encoding="utf-8")
        restored = receiver.ReceiverState(log_path=self.log_path)
        self.assertEqual(restored.messages[0]["event_id"], "legacy-event")
        self.assertEqual(restored.messages[0]["id"], "")
        response = await self.client.post("/callback", json={"msg": "legacy"})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.state.messages[-1]["id"], "")
        self.assertEqual(self.state.messages[-1]["msg"], "legacy")

    async def test_log_failure_still_returns_200_without_recording_a_message(self):
        self.state.log_path = Path(self.temp.name)
        response = await self.client.post("/callback", json={"id": "test-log-failure", "msg": "message"})
        self.assertEqual(response.status, 200)
        self.assertIn("could not save the message log", await response.text())
        self.assertEqual(self.state.received, 0)
        self.assertEqual(list(self.state.messages), [])

    async def test_publish_failure_still_returns_200_and_keeps_recorded_message(self):
        with patch.object(self.state, "publish", new=AsyncMock(side_effect=RuntimeError("test publish failure"))):
            with self.assertLogs(level="ERROR"):
                response = await self.client.post("/callback", json={"msg": "retained"})
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())["ok"])
        self.assertEqual(self.state.messages[-1]["msg"], "retained")
        self.assertEqual(json.loads(self.log_path.read_text(encoding="utf-8"))["msg"], "retained")

    async def test_events_decode_saved_carrier_and_serve_media(self):
        carrier_dir = Path(self.temp.name) / "carriers"
        media_dir = Path(self.temp.name) / "decoded"
        carrier_dir.mkdir()
        source = Image.new("RGB", (8, 8), (12, 34, 56))
        raw = BytesIO()
        source.save(raw, format="PNG")
        carrier = encode_bytes(raw.getvalue(), "png", password="demo", compress=2)
        carrier.save(carrier_dir / "video-demo_00001_.png", format="PNG")
        self.state.carrier_dir = carrier_dir
        self.state.media_dir = media_dir
        self.state.password = "demo"
        response = await self.client.get("/events")
        result = await response.json()
        self.assertEqual(result["media"][0]["extension"], "png")
        self.assertEqual(result["media"][0]["size"], len(raw.getvalue()))
        response = await self.client.get(result["media"][0]["url"])
        self.assertEqual(await response.read(), raw.getvalue())
