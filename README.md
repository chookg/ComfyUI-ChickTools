# ComfyUI-ChickTools

[中文说明](README_CN.md)

**NotifyMe** (`NotifyMeNode`) sends upstream text from a ComfyUI workflow to an HTTP callback and supports passing through any connected data type.

## Installation

Run from ComfyUI's `custom_nodes` directory:

```sh
git clone https://github.com/chookg/ComfyUI-ChickTools.git
cd ComfyUI-ChickTools
python -m pip install -r requirements.txt
```

Use the Python interpreter that runs ComfyUI, then restart ComfyUI and search for `Notify Me` in the node menu.

## Inputs

| Input | Description |
| --- | --- |
| `callback_url` | Required destination for the HTTP POST |
| `id` | Editable task identifier, sent unchanged as text; defaults to an empty string |
| `msg` | Optional STRING connection; sends an empty string when unconnected |
| `passthrough` | Optional input of any type; returned unchanged through the matching output after a successful callback |
| `allow_localhost` | Disabled by default; permits `127.0.0.1` or `::1` for local testing |

## Usage

```text
Text node → NotifyMe.msg
Upstream data → NotifyMe.passthrough → Downstream node
```

Set `callback_url` and your task `id`, then run. The node sends an HTTP POST with a JSON body containing only:

```json
{"id": "task-001", "msg": "Upstream text"}
```

The `msg` text is preserved exactly. Passthrough data stays inside the workflow and is not sent as a callback attachment. Only **HTTP 200** is accepted.

To notify after a particular operation, connect its output to `msg` or `passthrough`; notification runs after the connected upstream nodes finish.

Callbacks use public HTTP(S) destinations by default. A cloud instance requires a callback address reachable from that instance. Every queued run sends another notification. Connect and read timeouts are 15 seconds each, with no automatic retries.

[Text notification example](examples/notify_me_example.json) · [Empty message example](examples/notify_me_empty_example.json) · [License](LICENSE)
