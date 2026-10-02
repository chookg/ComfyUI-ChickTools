from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch

import requests

from plugin_loader import plugin
from chicktools.nodes.notify_me import NotifyMeNode
from chicktools.utils.callback_http import post_completion, _PinnedAdapter
from chicktools.utils.url_security import CallbackTarget

CALLBACK = "http://callback.example/finished"
MESSAGE = '  完成通知 🐥\n第二行\t"quoted" \\  '


class Receiver(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.calls.append((self.path, self.headers["Host"], self.headers["Content-Type"], json.loads(body)))
        if self.path == "/slow":
            time.sleep(0.2)
        status = int(self.path[1:]) if self.path[1:].isdigit() else 200
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "/200")
        self.end_headers()
        try:
            self.wfile.write(b"OK")  # deliberately plain text, never JSON
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class NotifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.node = NotifyMeNode()
        Receiver.calls.clear()

    def local_target(self, path="/200"):
        port = self.server.server_port
        # This transport fixture maps a synthetic hostname to its local receiver.
        return CallbackTarget("http://callback.example" + path, "callback.example", "127.0.0.1", port, "http", "callback.example")

    def test_real_post_preserves_text_and_accepts_plain_text_200(self):
        payload = object()
        with patch("chicktools.nodes.notify_me.validate_callback_url", return_value=self.local_target()):
            result = self.node.notify(CALLBACK, MESSAGE, passthrough=payload)
        self.assertIs(result[0], payload)
        self.assertEqual(Receiver.calls, [("/200", "callback.example", "application/json", {"id": "", "msg": MESSAGE})])

    def test_task_id_is_preserved_and_distinguishes_notifications(self):
        url = f"http://127.0.0.1:{self.server.server_port}/200"
        task_ids = ["000123", '  任务 🐥\t"quoted"  ', "task-002", ""]
        for task_id in task_ids:
            self.node.notify(url, MESSAGE, allow_localhost=True, id=task_id)
        self.assertEqual([call[-1] for call in Receiver.calls],
                         [{"id": task_id, "msg": MESSAGE} for task_id in task_ids])

    def test_non_text_id_never_sends(self):
        for task_id in (None, 123, True, [], {}, b"bytes"):
            with self.subTest(task_id=task_id), patch("chicktools.nodes.notify_me.post_completion") as post:
                with self.assertRaisesRegex(Exception, r"^请输入有效的任务编号（id 必须为文本）$") as raised:
                    self.node.notify(CALLBACK, MESSAGE, id=task_id)
                self.assertIs(type(raised.exception), Exception)
                post.assert_not_called()

    def test_passthrough_preserves_arbitrary_values_by_identity(self):
        for payload in (None, 42, "text", b"bytes", [], {}, object()):
            with self.subTest(payload_type=type(payload).__name__), patch(
                "chicktools.nodes.notify_me.validate_callback_url", return_value=self.local_target()
            ):
                result = self.node.notify(CALLBACK, passthrough=payload)
                self.assertEqual(len(result), 1)
                self.assertIs(result[0], payload)

    def test_local_callback_without_replacing_validation(self):
        url = f"http://127.0.0.1:{self.server.server_port}/200"
        with self.assertRaisesRegex(Exception, "公网地址") as raised:
            self.node.notify(url, MESSAGE)
        self.assertIs(type(raised.exception), Exception)
        self.assertEqual(Receiver.calls, [])
        self.assertEqual(self.node.notify(url, MESSAGE, allow_localhost=True), (None,))
        self.assertEqual(Receiver.calls[0][-1], {"id": "", "msg": MESSAGE})
        with self.assertRaisesRegex(Exception, "布尔值") as raised:
            self.node.notify(url, MESSAGE, allow_localhost="false")
        self.assertIs(type(raised.exception), Exception)

    def test_optional_message_and_blank_text_still_send(self):
        for kwargs in ({}, {"msg": ""}, {"msg": "  \n\t"}):
            with self.subTest(kwargs=kwargs), patch("chicktools.nodes.notify_me.validate_callback_url", return_value=self.local_target()):
                self.assertEqual(self.node.notify(CALLBACK, **kwargs), (None,))
                self.assertEqual(Receiver.calls[-1][-1], {"id": "", "msg": kwargs.get("msg", "")})
        self.assertEqual(len(Receiver.calls), 3)

    def test_non_text_message_never_sends(self):
        for msg in (None, 123, True, [], {}, b"bytes"):
            with self.subTest(msg=msg), patch("chicktools.nodes.notify_me.post_completion") as post:
                with self.assertRaisesRegex(Exception, r"^请输入有效的文本消息（msg 必须为文本）$") as raised:
                    self.node.notify(CALLBACK, msg)
                self.assertIs(type(raised.exception), Exception)
                post.assert_not_called()

    def test_exact_status_and_no_redirect(self):
        for status in (201, 202, 204, 302, 400, 500):
            with self.subTest(status=status):
                Receiver.calls.clear()
                with patch("chicktools.nodes.notify_me.validate_callback_url", return_value=self.local_target(f"/{status}")):
                    with self.assertRaisesRegex(Exception, rf"^回调请求失败（HTTP {status}）$") as raised:
                        self.node.notify(CALLBACK, MESSAGE)
                    self.assertIs(type(raised.exception), Exception)
                self.assertEqual(len(Receiver.calls), 1)

    def test_invalid_callback_never_sends(self):
        for callback in ("", "  ", None, 123):
            with self.subTest(callback=callback), patch("chicktools.nodes.notify_me.post_completion") as post:
                with self.assertRaisesRegex(Exception, r"^请输入有效的回调地址$") as raised:
                    self.node.notify(callback, MESSAGE)
                self.assertIs(type(raised.exception), Exception)
                post.assert_not_called()

    def test_security_errors_use_plain_exception(self):
        for url in ["file:///a", "http://127.0.0.1", "http://[broken", "http://a:wrong"]:
            with self.subTest(url=url), patch("chicktools.nodes.notify_me.post_completion") as post:
                with self.assertRaisesRegex(Exception, r"^请输入有效的回调地址：") as raised:
                    self.node.notify(url, MESSAGE)
                self.assertIs(type(raised.exception), Exception)
                post.assert_not_called()

    def test_network_errors_and_timeout_contract(self):
        for error in (requests.Timeout, requests.ConnectionError, requests.exceptions.SSLError):
            with self.subTest(error=error), patch("chicktools.nodes.notify_me.validate_callback_url", return_value=self.local_target()), patch(
                "chicktools.nodes.notify_me.post_completion", side_effect=error("secret query token")
            ) as post:
                with self.assertRaisesRegex(Exception, rf"^回调请求失败（{error.__name__}）$") as raised:
                    self.node.notify(CALLBACK, MESSAGE)
                self.assertIs(type(raised.exception), Exception)
                self.assertEqual(post.call_args.kwargs["timeout"], 15)

    def test_real_read_timeout(self):
        with self.assertRaises(requests.Timeout):
            post_completion(self.local_target("/slow"), MESSAGE, timeout=0.04)

    def test_real_connection_failure(self):
        # A bound socket that never listens reliably refuses a TCP connection.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            target = CallbackTarget(CALLBACK, "callback.example", "127.0.0.1", sock.getsockname()[1], "http", "callback.example")
            with self.assertRaises(requests.ConnectionError):
                post_completion(target, MESSAGE, timeout=0.5)

    def test_transport_ignores_ambient_proxy_and_never_resolves_original_host(self):
        original = socket.getaddrinfo
        queried = []
        def resolve(host, *args, **kwargs):
            queried.append(host)
            return original(host, *args, **kwargs)
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1"}), patch("socket.getaddrinfo", side_effect=resolve):
            self.assertEqual(post_completion(self.local_target(), MESSAGE), 200)
        self.assertTrue(queried)
        self.assertEqual(set(queried), {"127.0.0.1"})

    def test_tls_uses_original_hostname_for_certificate_and_sni(self):
        target = CallbackTarget("https://callback.example/done", "callback.example", "8.8.8.8", 443, "https", "callback.example")
        adapter = _PinnedAdapter(target)
        self.addCleanup(adapter.close)
        self.assertEqual(adapter.pool.host, "8.8.8.8")
        self.assertEqual(adapter.pool.assert_hostname, "callback.example")
        self.assertEqual(adapter.pool.conn_kw["server_hostname"], "callback.example")
