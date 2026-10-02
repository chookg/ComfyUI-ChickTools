# Carrier Format

ChickHideNode writes a lossless RGB PNG. The image carries one binary payload and
can be decoded without the ComfyUI runtime.

The payload starts with a four-byte big-endian header length. The header contains:

1. One byte: `0` for an unprotected payload or `1` for a password-protected payload.
2. For protected payloads, a 32-byte password check and a 16-byte random salt.
3. One byte containing the UTF-8 extension length, followed by the extension.
4. A four-byte big-endian payload length, followed by the payload bytes.

When a password is present, payload bytes are XORed with a SHA-256 counter stream
derived from the password and salt. The password check is verified before decoding.

Payload bits are written to the least significant bits of RGB channels. The supported
channel widths are 2, 6 and 8 bits. The top-left decoration area is excluded from the
payload so the carrier can display a title without changing its data.

The node uses extensions `png`, `wav` and `mp4`. WAV is PCM16. Video is H.264
with optional AAC audio. MP4 bytes are stored directly with their exact length; they are
not converted to an intermediate pixel image or stripped of trailing zero bytes.
Each carrier contains one file, with no embedded file name or multi-file archive.
An independent image batch yields multiple same-sized carriers.

Bit order is most-significant bit first, across row-major RGB channels. The excluded
rectangle is `floor(width * 0.40)` by `floor(height * 0.08)` at the top left.
The canvas starts at 640x640 and grows in 64-pixel steps until the packet fits.
The final channel group is zero-padded. `compress` selects LSB width, not a media codec
or a general-purpose compression level. The password stream concatenates SHA-256 hashes
of `UTF8(password + salt.hex() + decimal_counter)`, starting at counter zero; the stored
check hashes `UTF8(password + salt.hex())`. This format has no authenticated integrity tag.

The carrier preserves packaged bytes exactly. Media conversion has its own quality limits:
PNG quantizes IMAGE floats to 8 bits, WAV quantizes to signed PCM16, and H.264/AAC is lossy.
The node does not fetch or upload source media. FFmpeg receives only locally generated
temporary files, uses CPU encoding, and leaves no media files after the invocation finishes.

## Saved PNG metadata

The binary header stores the password check and random salt, never the plaintext password.
This is separate from ComfyUI PNG metadata: generic SaveImage and PreviewImage can embed the
entire execution prompt and editor workflow, including ChickHideNode's password input.
Use ChickSaveImage for carrier outputs. It omits the prompt and passes only AIGC provenance
metadata to the host saver without altering pixels, encrypted bytes or shared execution data.
The new PNG does not embed a recoverable editor workflow. Manually exported workflow JSON,
execution requests and old PNG files are outside this saving change.
