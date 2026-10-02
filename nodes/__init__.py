"""Independent ChickTools node implementations."""

from .chick_hide import ChickHideNode
from .chick_save import ChickSaveImage
from .chick_restore import ChickRestoreImage
from .notify_me import NotifyMeNode

NODE_CLASS_MAPPINGS = {
    "ChickHideNode": ChickHideNode,
    "ChickSaveImage": ChickSaveImage,
    "ChickRestoreImage": ChickRestoreImage,
    "NotifyMeNode": NotifyMeNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ChickHideNode": "小鸡节点 | Chick Hide",
    "ChickSaveImage": "小鸡载体保存（不写入密码元数据） | Chick Private Save",
    "ChickRestoreImage": "小鸡图片还原 | Chick Restore Image",
    "NotifyMeNode": "通知我 | Notify Me",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
