# Validation

Run the following commands from the repository directory using the Python interpreter
configured for your ComfyUI installation:

```sh
python -m pip install -r requirements.txt "av>=14"
python -X utf8 -m unittest discover -s tests -v
python -m compileall -q __init__.py nodes utils chick tests tools
```

The tests cover independent node registration and the carrier encoder,
HTTP status handling, text task identifiers, optional text messages, repeated notifications, timeouts, URL and DNS
validation, pinned connections, TLS hostname verification, and proxy isolation.
They use synthetic inputs and a local HTTP fixture without loading models.

Version 0.5.0 passed 55 unit tests, including PNG restoration of RGB/RGBA batches at all
supported LSB widths and rejection of incorrect passwords and non-image payloads.
The connected image example was also executed on CPU: LoadImage → ChickHideNode →
NotifyMeNode → ChickRestoreImage → ChickSaveImage. Its 256×192 landscape was recovered
pixel-for-pixel, the carrier used the bundled chick cover, both saved PNGs excluded
prompt/workflow metadata, and the loopback receiver accepted the message. The distributable
wheel includes the cover assets and passed a codec round trip after extraction.

The carrier tests cover all supported LSB widths, image round trips, password
verification, and invalid batch input handling. Media tests independently read generated
MP4 files with PyAV to verify frame count, frame order, dimensions, timestamps, audio
channels and duration. Fixtures use up to eight 16x16 frames and two seconds of synthetic
audio. WAV tests check PCM values, sample rate and trailing silence. Failure and timeout
tests verify temporary-file cleanup and that failed audio encoding is never retried silently.

The compatibility check also exercises both directions against an independently installed
reference decoder/encoder during development; that reference is not packaged or imported
by this repository. Version 0.3.0 was also checked by passing an eight-frame MP4 with audio
through a reference decode node at all three LSB widths, with and without passwords:
the exported file bytes, eight frames, 8 fps and audio were recovered. Standalone WAV,
PNG files were recovered byte-for-byte. The checked reference exports a WAV file
without populating its AUDIO output; consumers can load the recovered file separately.

## Optional ComfyUI integration test

Install this repository as `ComfyUI-ChickTools` in your ComfyUI `custom_nodes` directory.
Replace `/path/to/ComfyUI` with your installation directory:

```sh
python -X utf8 tools/smoke_comfy.py --comfy /path/to/ComfyUI
```

The test starts an isolated CPU process on port 8191, with its own user, output and
temporary directories and an in-memory database. Use `--port` to choose another available port.

It runs twelve workflows: eight carrier workflows (image and repeat-image, silent video,
video with audio, audio, an independent image batch, and a password-protected saved carrier
twice) plus four standalone notifications (connected text, a repeated queued run, no message
connection, and whitespace-only text). The media workflows connect ChickHide directly to
ChickSaveImage. The text workflows connect PrimitiveStringMultiline to NotifyMe.msg.
It downloads the actual PNGs, decodes their payloads and checks images, WAV samples and
MP4 frames/audio, as well as the exact four JSON callback bodies containing id and msg.
Notification cases verify Unicode task IDs with leading zeros, a changed task ID, and
backward compatibility with a workflow that omits id. Receiver tests also verify repeated
task IDs remain distinct events and that old logs restore with an empty task ID.
Every carrier request deliberately includes a workflow snapshot and an additional metadata field;
the saved PNG must contain only the synthetic AIGC provenance marker. Protected payloads
must decode with the correct password and reject both missing and incorrect passwords.
The repeated protected run also exercises cached encoder output.
The audio file is synthesized in an isolated input directory and loaded by LoadAudio.
The test enables allow_localhost and posts to an actual loopback HTTP receiver.
URL validation and the HTTP transport are exercised directly without replacement.
The default configuration still requires public HTTP(S) destinations.
Receiver tests check exact Unicode/empty message logs, invalid requests and log-write failure.

The test loads no models and stops its own server when finished. Generated reports,
logs and preview images are stored under the ignored `.local/smoke` directory.

Version 0.4.2 passed the 51 unit tests and all twelve CPU workflows on ComfyUI 0.37.0.
No models were loaded. This verifies the local ComfyUI saving contract; installations that
independently add PNG metadata should check their actual returned files as well.
