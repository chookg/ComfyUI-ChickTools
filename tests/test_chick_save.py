import copy
import unittest

from plugin_loader import plugin
import chicktools.nodes.chick_save as chick_save


class PrivateSaverTests(unittest.TestCase):
    def test_schema_does_not_request_prompt_metadata(self):
        schema = plugin.NODE_CLASS_MAPPINGS["ChickSaveImage"].INPUT_TYPES()
        self.assertNotIn("prompt", schema.get("hidden", {}))
        self.assertEqual(schema["hidden"]["extra_pnginfo"], "EXTRA_PNGINFO")
        self.assertEqual(plugin.NODE_DISPLAY_NAME_MAPPINGS["ChickSaveImage"],
                         "小鸡载体保存（不写入密码元数据） | Chick Private Save")

    def test_allowlist_keeps_aigc_without_mutating_shared_metadata(self):
        captured = {}
        original = chick_save._ComfySaveImage.save_images

        def host_save(node, images, filename_prefix="ComfyUI", prompt=None,
                      extra_pnginfo=None, **kwargs):
            captured.update(images=images, filename_prefix=filename_prefix,
                            prompt=prompt, extra_pnginfo=extra_pnginfo, kwargs=kwargs)
            return {"ui": {"images": [{"filename": "carrier.png"}]}}

        chick_save._ComfySaveImage.save_images = host_save
        try:
            node = plugin.NODE_CLASS_MAPPINGS["ChickSaveImage"]()
            prompt = {"2": {"class_type": "ChickHideNode",
                             "inputs": {"password": "secret-password"}}}
            metadata = {
                "workflow": {"nodes": [{"id": 2, "widgets_values": ["secret-password"]}]},
                "AIGC": {"Label": "1"},
            }
            before_prompt, before_metadata = copy.deepcopy(prompt), copy.deepcopy(metadata)
            result = node.save_images(["pixels"], "carrier", prompt, metadata)
        finally:
            chick_save._ComfySaveImage.save_images = original

        self.assertEqual(result["ui"]["images"][0]["filename"], "carrier.png")
        self.assertEqual(captured["prompt"], None)
        self.assertEqual(captured["extra_pnginfo"], {"AIGC": {"Label": "1"}})
        self.assertNotIn("secret-password", repr(captured["extra_pnginfo"]))
        self.assertEqual(prompt, before_prompt)
        self.assertEqual(metadata, before_metadata)


if __name__ == "__main__":
    unittest.main()
