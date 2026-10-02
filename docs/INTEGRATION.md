# Preparing an installation test

The four nodes remain independent. Use the Python interpreter from the target ComfyUI.

## Read the installed node interfaces

```sh
python tools/prepare_workflow.py --base-url http://127.0.0.1:8188 --out-dir .local/preparation
```

Alternatively, export the target instance's `/object_info` response through its authenticated
session and inspect the saved JSON offline:

```sh
python tools/prepare_workflow.py --object-info /path/to/object_info.json --out-dir .local/preparation
```

Choose a new output directory on each run. Reports include node presence and output slots,
but omit schema defaults, endpoints and credentials. The tool only reads schema data;
it does not queue workflows, install nodes or send notifications. Exit code 0 means the
carrier and standalone notification templates are ready; 2 means at least one has missing
or incompatible prerequisites. The text example has its own readiness flag because its
sample source, PrimitiveStringMultiline, is not required for the notification node itself.
None of these flags establishes that the instance executed a workflow successfully.

## Generated workflows

Each available workflow is written in both API and canvas JSON formats:

- `carrier-smoke`: `EmptyImage(16x16) -> ChickHideNode -> ChickSaveImage`.
- `notify-text-smoke`: `PrimitiveStringMultiline -> NotifyMeNode.msg` and the same STRING value
  through `NotifyMeNode.passthrough`.
- `notify-empty-smoke`: NotifyMeNode alone, with its optional msg socket unconnected.

The carrier template follows the Duck media wiring: IMAGE frames enter `images`, optional
AUDIO enters `audio`, and `chick_image` connects to ChickSaveImage. Text payload encoding
is omitted. Download the saved PNG and decode it with `chick.codec.decode_bytes`; it should
contain a 16x16 blue image. When a password is set, check that the payload requires that
password and that PNG metadata contains no execution prompt, workflow or password.

ChickSaveImage inherits the target installation's SaveImage implementation, omits its
hidden `prompt` input and filters `extra_pnginfo` to preserve only `AIGC` provenance.
Prompt and workflow snapshots are never forwarded to the PNG writer.

The notification templates are independent of the carrier template and SaveImage outputs.
Fill `callback_url` with your receiver and `id` with your task identifier before executing.
The text example sends exactly `{"id":"demo-task-001","msg":"Sample message"}`;
the unconnected example sends `{"id":"demo-task-001","msg":""}`. Older workflows that omit
`id` send an empty string for that field. The receiver must
return HTTP 200. Queue the same notification again to verify another POST is sent even
when the text source is cached. Unicode, newlines and whitespace must be preserved.

For local callbacks, use the [bundled receiver](LOCAL_CALLBACK.md) and enable
`allow_localhost` in NotifyMe. This permits literal 127.0.0.1 or ::1 destinations.

For real workflows, connect the STRING output whose completion should precede the
notification. The node sends that string as msg without interpreting URLs or JSON inside
it. The separate optional wildcard `passthrough` socket accepts any ComfyUI value; after the
callback succeeds, that exact object is returned through the wildcard output. An unconnected
passthrough output is `None`, and an unconnected msg socket does not establish ordering with
other workflow branches.

## Upgrade from 0.3.x

Restart ComfyUI, recreate old NotifyMe nodes and reconnect upstream text to msg. The old
image and preview_url inputs and typed IMAGE output have been removed; the current node has
a wildcard passthrough input/output. Connect carrier images directly to ChickSaveImage, and
remove any old ChickHide text_input connections.

## Installation handoff

Provide the repository or a source ZIP with its exact commit and SHA-256, the dependency
list, the four registered node names, and the minimal workflows. A private repository
requires access to be arranged before installation. Registry publication additionally
requires a real PublisherId; an empty placeholder is not a completed registration.

Keep credentials, private endpoint values and environment-specific reports outside tracked
files. Examples contain synthetic data; generated templates leave callback_url empty.
The dedicated local example explicitly uses the loopback receiver address.
