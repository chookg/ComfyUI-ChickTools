# ComfyUI-ChickTools

[English](README.md)

**通知我 / NotifyMe**（`NotifyMeNode`）将 ComfyUI 工作流中的上游文本发送到 HTTP 回调地址，并支持任意类型数据透传。

## 安装

在 ComfyUI 的 `custom_nodes` 目录执行：

```sh
git clone https://github.com/chookg/ComfyUI-ChickTools.git
cd ComfyUI-ChickTools
python -m pip install -r requirements.txt
```

请使用 ComfyUI 实际运行的 Python，安装后重启 ComfyUI，搜索“通知我”或 `Notify Me`。

## 参数

| 输入 | 说明 |
| --- | --- |
| `callback_url` | 必填，接收 HTTP POST 的地址 |
| `id` | 可手动填写的任务编号，按文本原样发送；留空时发送空字符串 |
| `msg` | 可选 STRING 连线输入；未连接时发送空字符串 |
| `passthrough` | 可选任意类型输入；回调成功后从同名输出原样传递 |
| `allow_localhost` | 默认关闭；本机调试时允许 `127.0.0.1` 或 `::1` |

## 用法

```text
文本节点 → NotifyMe.msg
上游数据 → NotifyMe.passthrough → 下游节点
```

填写 `callback_url` 和任务 `id` 后运行，请求使用 HTTP POST，JSON 正文仅包含：

```json
{"id": "task-001", "msg": "上游文本"}
```

`msg` 中的文本原样发送。`passthrough` 数据仅在工作流内部传递，不作为回调附件发送。只有 **HTTP 200** 被视为成功。

需要在目标处理完成后通知时，将其输出接到 `msg` 或 `passthrough`；通知会在相连的上游执行完成后发送。

回调默认使用公网 HTTP(S) 地址。云端运行时，回调地址需从云端可访问。每次排队运行都会再次发送通知；连接与读取超时各为 15 秒，无自动重试。

[文本通知示例](examples/notify_me_example.json) · [空消息示例](examples/notify_me_empty_example.json) · [许可证](LICENSE)
