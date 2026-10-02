# 本地回调测试

接收服务监听本机 `127.0.0.1`，使用插件已有的 Pillow 和载体解码器显示测试结果。
在仓库目录使用 ComfyUI 的 Python 运行：

```sh
python tools/local_callback_server.py --port 8765 \
  --carrier-dir /path/to/ComfyUI/output/ChickTools \
  --password demo-password
```

浏览器打开 `http://127.0.0.1:8765/`，点击“开启监听”，页面通过 WebSocket 显示最近 100 条消息，以及载体解码出的 PNG、MP4 或 WAV。
新结果直接追加，视频保持播放；点击“停止监听”暂停页面更新，再次开启时补上已有结果。接收服务持续接收回调。
完整消息以 JSONL 追加保存到 `.local/callback-received.jsonl`，可用 `--log` 指定路径。
重启服务时从磁盘日志恢复消息和计数。按 Ctrl+C 停止服务。

`--carrier-dir` 指向 ComfyUI 输出载体 PNG 所在目录，`--password` 是 ChickHideNode
使用的测试密码。服务会扫描新 PNG，解码载体内的原始媒体，并在结果页提供图片、视频或音频控件；
密码只用于本地解码，不会显示在页面或写回媒体文件。

更新插件并重启 ComfyUI 后，导入
[`notify_me_local_example.json`](../examples/notify_me_local_example.json)，或手动接线：

`文本节点 STRING → NotifyMe.msg`

- callback_url：`http://127.0.0.1:8765/callback`
- id：填写任务编号，如 `demo-task-001`；留空时发送空字符串。
- allow_localhost：开启（默认关闭，在节点高级参数中）。
- msg：可选；不接线发送 `{"id":"demo-task-001","msg":""}`。

点击运行后，接收页面应显示填写的任务 id 和准确的文本，包括中文、换行和空格。
同一任务 id 的多次通知会分别显示；日志中的 `event_id` 是接收记录编号，与任务 id 分开。
重复运行相同工作流会再次发送通知。当前接收服务用于 HTTP 200 测试：
`POST /callback` 固定返回 200，有效消息写入日志并通过 WebSocket 推送。
NotifyMe 收到 200 后可继续执行后续节点。
请求校验、日志保存或推送发生异常时，该测试接口也返回 200，响应正文保留错误信息；
确认接收结果时同时查看页面记录。页面、健康检查和媒体接口照常响应。

服务接口：`POST /callback` 接收 `{"id":"demo-task-001","msg":"文本"}`（兼容省略 id 的旧请求）；`GET /events` 返回消息；
`GET /health` 返回状态和本次启动的接收数量。单次请求正文上限为 1 MiB。
所有测试都无需模型。

要同时查看小鸡节点和 NotifyMe，导入
[`chick_notify_local_example.json`](../examples/chick_notify_local_example.json)。
上方分支保存 16×16 图片载体，下方分支发送固定测试文本；两条分支独立执行。

allow_localhost 只额外允许字面量 `127.0.0.1` 和 `::1`，不开放其他内网地址。
回环地址指向运行 ComfyUI 的机器，因此这个示例适用于本机 ComfyUI；
远程 ComfyUI 应使用它能访问的接收地址。

视频结果测试：导入 [`chick_notify_video_example.json`](../examples/chick_notify_video_example.json)。
它使用 `ImageBatchTestPattern` 生成 8 帧 64×64 测试图案，再连接
`ChickHideNode → ChickSaveImage` 生成带密码的 MP4 载体，同时将文本发送到 NotifyMe。
启动接收服务时使用同一个 `demo-password`，运行后结果页会显示回调文本和解码后的视频。
