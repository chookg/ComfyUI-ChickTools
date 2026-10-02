# Examples

All examples are importable ComfyUI canvas workflows and require no models.

`chick_image_roundtrip_example.json` connects the two main nodes and restores the original
image at the end: LoadImage → ChickHideNode → NotifyMeNode.passthrough → ChickRestoreImage
→ ChickSaveImage. A separate ChickSaveImage writes the carrier from NotifyMe's output.
Copy `assets/roundtrip-input.png` to the ComfyUI input directory as
`chicktools-roundtrip-input.png`, or choose your own uploaded image. Start the local receiver
and use the same `demo-password` in the encoder and restore node. The final preview is decoded
from the carrier, and both savers omit prompt/workflow/password metadata.

`chick_notify_local_example.json` displays both main nodes in one canvas: a 16x16 image
passes through ChickHide and ChickSaveImage, while a separate text branch sends msg through
NotifyMe to the local receiver. The branches are independent; the text is a sample message,
not a claim that another branch has completed. Start the local receiver before running it.

`chick_notify_video_example.json` is the model-free video test: `ImageBatchTestPattern` creates
eight 64x64 numbered frames, ChickHide packages them as an encrypted MP4, ChickSaveImage writes
the carrier PNG, and the separate text branch sends the result message through NotifyMe. The
synthetic password is `demo-password`; point the local receiver at the ComfyUI output directory
with the same password to see the decrypted MP4 in its web page.

- `notify_me_example.json`: Text (Multiline) connects to the optional NotifyMe `msg` socket.
- `notify_me_empty_example.json`: NotifyMe without a text connection sends `{"id":"demo-task-001","msg":""}`.
- `notify_me_local_example.json`: posts to `http://127.0.0.1:8765/callback` with allow_localhost enabled.
  Start the [local receiver](../docs/LOCAL_CALLBACK.md) first.

Fill in callback_url and your task id before running the first two notification examples. Their callback must be public
and return HTTP 200. Text is sent as the JSON msg value, preserving newlines and whitespace.
The notification node also has a wildcard passthrough input/output. Connect any value to
passthrough to continue the workflow with that exact value after the callback succeeds.
For local verification, use the explicit allow_localhost option and the bundled receiver.
The switch permits only the literal loopback addresses 127.0.0.1 and ::1.

The following media workflows make no HTTP requests:

- `chick_image_example.json`: two 8x8 images, encoded as independent PNG payloads.
- `chick_audio_example.json`: 0.125 seconds of synthetic silence in a WAV payload.
- `chick_video_example.json`: eight 16x16 frames at 8 fps, with synthetic audio in an MP4 payload.

Media wiring follows the Duck encoder: IMAGE frames connect to `images`, optional AUDIO
connects to `audio`, and the carrier IMAGE connects to ChickSaveImage. Text encoding is omitted.
The audio/video examples use ComfyUI's built-in EmptyAudio node. Substitute LoadAudio
or another standard AUDIO producer for real sound. Save carriers as PNG without resizing.

Each media example uses ChickSaveImage, which excludes Prompt, workflow and password
metadata from the PNG. Displayed carrier previews show the carrier, not the original media.
