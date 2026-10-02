import socket
import unittest
from unittest.mock import patch

from plugin_loader import plugin
from chicktools.utils.url_security import CallbackURLValidationError, validate_callback_url


def answer(address):
    return (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))


class URLTests(unittest.TestCase):
    def test_public_literals(self):
        for url in ("https://8.8.8.8/path?q=1", "https://[2606:4700:4700::1111]/"):
            with self.subTest(url=url):
                self.assertEqual(validate_callback_url(url).url, url)

    def test_local_testing_requires_explicit_flag_and_literal_loopback(self):
        for url, address in (("http://127.0.0.1:8765/callback", "127.0.0.1"),
                             ("http://[::1]:8765/callback", "::1")):
            with self.subTest(url=url):
                with self.assertRaises(CallbackURLValidationError):
                    validate_callback_url(url)
                target = validate_callback_url(url, allow_localhost=True)
                self.assertEqual((target.url, target.address, target.port), (url, address, 8765))

    def test_local_option_does_not_allow_other_private_or_fake_addresses(self):
        for host in ("127.0.0.2", "10.0.0.1", "192.168.1.1", "169.254.169.254", "198.18.0.1",
                     "localhost", "0.0.0.0", "[::ffff:127.0.0.1]"):
            with self.subTest(host=host), self.assertRaises(CallbackURLValidationError):
                validate_callback_url("http://" + host, allow_localhost=True)
        with patch("socket.getaddrinfo", return_value=[answer("127.0.0.1")]):
            with self.assertRaises(CallbackURLValidationError):
                validate_callback_url("http://callback.example", allow_localhost=True)

    def test_blocked_addresses(self):
        for host in ("127.0.0.1", "localhost", "localhost.", "a.localhost", "10.0.0.1", "172.16.0.1",
                     "192.168.1.1", "169.254.169.254", "100.64.0.1", "198.18.0.1", "0.0.0.0",
                     "224.0.0.1", "[::1]", "[::]", "[fc00::1]", "[fe80::1]", "[::ffff:127.0.0.1]",
                     "[64:ff9b::7f00:1]", "metadata.google.internal"):
            with self.subTest(host=host), self.assertRaises(CallbackURLValidationError):
                validate_callback_url("http://" + host)

    def test_malformed_urls(self):
        for url in ("ftp://8.8.8.8", "file:///x", "gopher://8.8.8.8", "http://", "https://a:0",
                    "http://a:99999", "http://a:wrong", "http://[broken", "http://user:pass@8.8.8.8",
                    "http://8.8.8.8/#fragment", "http://8.8.8.8/a\nb", "http://8.8.8.8\\foo"):
            with self.subTest(url=url), self.assertRaises(CallbackURLValidationError):
                validate_callback_url(url)

    def test_dns_mixed_private_answers_rejected(self):
        with patch("socket.getaddrinfo", return_value=[answer("8.8.8.8"), answer("127.0.0.1")]):
            with self.assertRaises(CallbackURLValidationError):
                validate_callback_url("https://callback.example")

    def test_dns_failure_fails_closed(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("failed")):
            with self.assertRaises(CallbackURLValidationError):
                validate_callback_url("https://callback.example")

    def test_dns_resolved_once_and_saved(self):
        with patch("socket.getaddrinfo", return_value=[answer("8.8.8.8")]) as resolver:
            target = validate_callback_url("https://callback.example/finished?q=1")
        resolver.assert_called_once()
        self.assertEqual(target.address, "8.8.8.8")
        self.assertEqual(target.hostname, "callback.example")
        self.assertEqual(target.url, "https://callback.example/finished?q=1")

    def test_legacy_numeric_host_resolved_and_rejected(self):
        with patch("socket.getaddrinfo", return_value=[answer("127.0.0.1")]):
            with self.assertRaises(CallbackURLValidationError):
                validate_callback_url("http://2130706433")
