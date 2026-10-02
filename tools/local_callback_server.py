"""Loopback callback receiver with live carrier previews. Run with ComfyUI's Python."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import logging
from pathlib import Path
import sys
from uuid import uuid4

from aiohttp import web
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chick.codec import CarrierCodecError, decode_bytes


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NotifyMe 本地测试结果</title>
<style>
body{font:16px system-ui;margin:32px auto;max-width:860px;padding:0 20px;background:#f5f6fa;color:#18202b}
article{background:white;padding:20px;margin:16px 0;border:1px solid #e0e5ed;border-radius:10px}
pre{white-space:pre-wrap;overflow-wrap:anywhere}time,.muted{color:#536275;font-size:14px}
code{background:#e9edf4;padding:4px}video,img{display:block;max-width:100%;max-height:480px;margin-top:14px;background:#111}
video{width:100%;min-height:180px}audio{width:100%;margin-top:14px}
button{font:inherit;background:#245dba;color:white;border:0;border-radius:6px;padding:9px 16px;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}.error{color:#a21d2a}a{color:#245dba}
</style>
<h1>本地测试结果</h1><p>回调地址：<code id="url"></code></p>
<p class="muted">测试模式：回调固定返回 HTTP 200，NotifyMe 可继续执行后续节点。处理详情见接收记录和响应正文。</p>
<p>点击开启监听后，新结果会自动追加，正在播放的视频会保持播放。</p>
<button id="listen" type="button" aria-pressed="false">开启监听</button> <span id="connection" role="status">尚未开启监听</span>
<p id="status" class="muted"></p>
<h2>回调内容</h2><div id="messages"><p id="messages-empty" class="muted">等待 NotifyMe 消息…</p></div>
<h2>解码媒体</h2><p class="muted">载体从指定的本地输出目录读取；回调包含任务 id 和文本 msg，两条分支独立执行。</p>
<div id="media"><p id="media-empty" class="muted">等待载体 PNG…</p></div>
<script src="/viewer.js" defer></script></html>"""


def now():
    return datetime.now(timezone.utc).isoformat()


class ReceiverState:
    def __init__(self, log_path=None, carrier_dir=None, media_dir=None, password=""):
        self.log_path = Path(log_path) if log_path is not None else None
        self.carrier_dir = Path(carrier_dir).resolve() if carrier_dir is not None else None
        self.media_dir = Path(media_dir or ".local/decoded-media").resolve()
        self.password = password
        self.messages = deque(maxlen=100)
        self.received = 0
        self.media = {}
        self.files = {}
        self.clients = set()
        self.scan_lock = asyncio.Lock()
        self.publish_lock = asyncio.Lock()
        self.revision = 0
        self.session = uuid4().hex
        if self.log_path is not None and self.log_path.is_file():
            with self.log_path.open(encoding="utf-8") as log:
                for index, line in enumerate(log):
                    try:
                        record = json.loads(line)
                        if not isinstance(record.get("msg"), str):
                            continue
                        if "event_id" not in record:
                            # Earlier logs used id for the receiver's event identity.
                            record["event_id"] = record.pop("id", sha256(f"{index}:{line}".encode()).hexdigest())
                            record["id"] = ""
                        self.messages.append(record)
                        self.received += 1
                    except (ValueError, AttributeError):
                        continue

    def snapshot(self):
        return {"ok": True, "service": "chicktools-callback-receiver",
                "session": self.session, "revision": self.revision,
                "received": self.received, "messages": list(self.messages),
                "media": list(self.media.values())}

    def receive(self, message, task_id=""):
        record = {"event_id": uuid4().hex, "id": task_id,
                  "received_at": now(), "path": "/callback", "msg": message}
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8", newline="\n") as log:
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.messages.append(record)
        self.received += 1
        self.revision += 1

    def _scan(self):
        """Decode off the event loop; publish only complete, stable file versions."""
        records, files = [], {}
        if self.carrier_dir is None:
            return records, files
        self.media_dir.mkdir(parents=True, exist_ok=True)
        candidates = []
        for path in self.carrier_dir.glob("*.png"):
            try:
                if path.resolve().parent == self.carrier_dir:
                    stat = path.stat()
                    candidates.append((stat.st_mtime_ns, path, stat.st_size))
            except OSError:
                continue
        for modified, path, size in sorted(candidates)[-100:]:
            key = sha256(f"{path.name}:{modified}:{size}".encode()).hexdigest()
            if key in self.media:
                continue
            record = {"id": key, "source": path.name, "extension": "", "size": 0, "decoded_at": now()}
            try:
                source = path.read_bytes()
                current = path.stat()
                if (current.st_mtime_ns, current.st_size) != (modified, size):
                    continue
                with Image.open(BytesIO(source)) as image:
                    payload, extension = decode_bytes(image, self.password)
                extension = extension.lower().lstrip(".")
                if extension not in {"png", "jpg", "jpeg", "gif", "webp", "mp4", "webm", "wav", "mp3", "ogg"}:
                    raise CarrierCodecError("unsupported preview format")
                name = f"{key}.{extension}"
                target = self.media_dir / name
                temporary = self.media_dir / f"{key}.tmp"
                temporary.write_bytes(payload)
                temporary.replace(target)
                original = self.media_dir / f"{key}.carrier.png"
                original.write_bytes(source)
                record.update(extension=extension, size=len(payload), url="/media/" + name,
                              carrier_url="/media/" + original.name)
                files[name] = target
                files[original.name] = original
            except (OSError, ValueError) as exc:
                # A partially written PNG can be retried after its size or mtime changes.
                record["error"] = str(exc)
            records.append(record)
        return records, files

    async def scan(self):
        async with self.scan_lock:
            try:
                records, files = await asyncio.to_thread(self._scan)
            except OSError:
                return False
            for record in records:
                self.media[record["id"]] = record
            self.files.update(files)
            if records:
                self.revision += 1
            return bool(records)

    async def publish(self):
        async with self.publish_lock:
            snapshot = self.snapshot()
            async def send(client):
                try:
                    await asyncio.wait_for(client.send_json(snapshot), timeout=2)
                except (OSError, RuntimeError, asyncio.TimeoutError):
                    self.clients.discard(client)
            await asyncio.gather(*(send(client) for client in tuple(self.clients)))


def create_app(state=None, scan_interval=1.0):
    state = state or ReceiverState()
    app = web.Application(client_max_size=1024 * 1024)

    async def home(request):
        return web.Response(text=PAGE, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def script(request):
        return web.FileResponse(Path(__file__).with_name("local_results.js"), headers={"Cache-Control": "no-store"})

    async def receive_callback(request):
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType(text="use application/json")
        try:
            body = json.loads((await request.read()).decode("utf-8"))
        except (UnicodeError, ValueError):
            raise web.HTTPBadRequest(text="request body must be UTF-8 JSON")
        if (not isinstance(body, dict) or set(body) not in ({"msg"}, {"id", "msg"})
                or not isinstance(body["msg"], str) or not isinstance(body.get("id", ""), str)):
            raise web.HTTPBadRequest(text='body must be {"id": string, "msg": string}; id is optional')
        try:
            state.receive(body["msg"], body.get("id", ""))
        except OSError:
            raise web.HTTPInternalServerError(text="could not save the message log")
        await state.publish()
        return web.json_response({"ok": True})

    async def callback(request):
        # Keep the requested test status even if validation or storage fails.
        try:
            response = await receive_callback(request)
        except web.HTTPException as exc:
            response = web.Response(text=exc.text, content_type="text/plain")
        except Exception:
            logging.exception("Local callback processing failed")
            response = web.json_response({"ok": False, "error": "callback processing failed"})
        response.set_status(200)
        return response

    async def events(request):
        if await state.scan():
            await state.publish()
        return web.json_response(state.snapshot(), headers={"Cache-Control": "no-store"})

    async def health(request):
        return web.json_response({"ok": True, "service": "chicktools-callback-receiver", "received": state.received})

    async def media(request):
        target = state.files.get(request.match_info["name"])
        if target is None or not target.is_file():
            raise web.HTTPNotFound()
        # Range requests allow seeking without reading the whole video into memory.
        return web.FileResponse(target, headers={"X-Content-Type-Options": "nosniff"})

    async def websocket(request):
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
        await ws.prepare(request)
        state.clients.add(ws)
        try:
            await ws.send_json(state.snapshot())
            async for _ in ws:
                pass
        finally:
            state.clients.discard(ws)
        return ws

    async def watch():
        while True:
            await asyncio.sleep(scan_interval)
            if await state.scan():
                await state.publish()

    async def lifecycle(app):
        await state.scan()
        watcher = asyncio.create_task(watch())
        yield
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher

    async def shutdown(app):
        await asyncio.gather(*(ws.close(code=1001) for ws in tuple(state.clients)))

    app.cleanup_ctx.append(lifecycle)
    app.on_shutdown.append(shutdown)
    app.add_routes([web.get("/", home), web.get("/viewer.js", script),
                    web.post("/callback", callback), web.get("/events", events),
                    web.get("/health", health), web.get("/ws", websocket), web.get("/media/{name}", media)])
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log", type=Path, default=Path(".local/callback-received.jsonl"))
    parser.add_argument("--carrier-dir", type=Path, help="directory containing ChickSaveImage carrier PNGs")
    parser.add_argument("--password", default="", help="local demo carrier password")
    parser.add_argument("--media-dir", type=Path, default=Path(".local/decoded-media"))
    args = parser.parse_args()
    state = ReceiverState(args.log, args.carrier_dir, args.media_dir, args.password)
    print(f"Result viewer: http://{args.host}:{args.port}/", flush=True)
    web.run_app(create_app(state), host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
