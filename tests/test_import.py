import math
import unittest

from plugin_loader import plugin


class RegistrationTests(unittest.TestCase):
    def test_independent_nodes(self):
        self.assertEqual(set(plugin.NODE_CLASS_MAPPINGS), {"ChickHideNode", "ChickSaveImage", "ChickRestoreImage", "NotifyMeNode"})
        self.assertEqual(set(plugin.NODE_DISPLAY_NAME_MAPPINGS), set(plugin.NODE_CLASS_MAPPINGS))

    def test_chick_node_is_independently_registered(self):
        node = plugin.NODE_CLASS_MAPPINGS["ChickHideNode"]()
        self.assertEqual(node.RETURN_NAMES, ("chick_image",))
        schema = node.INPUT_TYPES()
        self.assertEqual(set(schema["optional"]), {"images", "audio"})
        self.assertEqual(list(schema["required"]), ["password", "title", "fps", "compress", "combine_video"])
        self.assertEqual(schema["required"]["fps"][1]["default"], 16)
        self.assertTrue(schema["required"]["combine_video"][1]["default"])

    def test_private_saver_is_independently_registered(self):
        node = plugin.NODE_CLASS_MAPPINGS["ChickSaveImage"]()
        schema = node.INPUT_TYPES()
        self.assertNotIn("prompt", schema.get("hidden", {}))
        self.assertEqual(schema["hidden"]["extra_pnginfo"], "EXTRA_PNGINFO")

    def test_notice_runs_on_every_queue(self):
        node = plugin.NODE_CLASS_MAPPINGS["NotifyMeNode"]
        self.assertTrue(math.isnan(node.IS_CHANGED()))
        self.assertTrue(node.OUTPUT_NODE)
        self.assertEqual(node.RETURN_TYPES, ("*",))
        self.assertEqual(node.RETURN_NAMES, ("passthrough",))
        schema = node.INPUT_TYPES()
        self.assertEqual(set(schema["required"]), {"callback_url"})
        self.assertEqual(schema["optional"]["msg"], ("STRING", {"forceInput": True}))
        self.assertEqual(schema["optional"]["passthrough"], ("*", {"forceInput": True}))
        self.assertFalse(schema["optional"]["allow_localhost"][1]["default"])
        self.assertEqual(schema["optional"]["id"][0], "STRING")
        self.assertEqual(schema["optional"]["id"][1]["default"], "")
        self.assertFalse(schema["optional"]["id"][1].get("forceInput", False))
        widgets = [key for group in ("required", "optional") for key, field in schema[group].items()
                   if not field[1].get("forceInput", False)]
        self.assertEqual(widgets, ["callback_url", "allow_localhost", "id"])
