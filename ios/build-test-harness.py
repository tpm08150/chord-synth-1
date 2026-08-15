#!/usr/bin/env python3
"""Generate a browser test page for the iOS MIDI shim.

Produces `_iostest.html` at the repo root: the real synth, with midi-bridge.js injected
and a mock of the native side attached. Lets the whole bridge be exercised in a desktop
browser without Xcode or a device.

    python3 ios/build-test-harness.py
    # then open http://localhost:8123/_iostest.html

The mock exposes:
    window.__native.sent          every {op,...} the shim posted
    window.__native.DEVICES       the device list it answers "init" with
    window.__native.incoming(id, bytes)   deliver an inbound MIDI message
    window.__native.devices(list)         push a new device list

It also hides the browser's real Web MIDI, so the shim installs the way it would under
WebKit, where the API simply doesn't exist.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "patchwork-chord-synth.html"
SHIM = ROOT / "ios" / "midi-bridge.js"
OUT = ROOT / "_iostest.html"

MARKER = '<script>\n(() => {\n"use strict";'

HARNESS = """<script>
(() => {
  Object.defineProperty(navigator, "requestMIDIAccess",
    {value: undefined, configurable: true, writable: true});
  const sent = [];
  const DEVICES = [
    {id: "src-1", name: "EP-133 K.O. II", type: "input"},
    {id: "dst-1", name: "EP-133 K.O. II", type: "output"}
  ];
  window.__native = {
    sent, DEVICES,
    incoming(port, bytes){ window.__patchworkMIDI.onMessage(port, bytes); },
    devices(list){ window.__patchworkMIDI.onDevices(list); }
  };
  window.webkit = { messageHandlers: { patchworkMIDI: { postMessage(m){
    sent.push(m);
    // CoreMIDI enumeration is quick, so answer init promptly
    if (m.op === "init") setTimeout(() => window.__patchworkMIDI.onDevices(DEVICES), 4);
  } } } };
})();
</script>
<script>
%s
</script>
"""


def main():
    if not PAGE.exists() or not SHIM.exists():
        sys.exit("expected patchwork-chord-synth.html and ios/midi-bridge.js")
    page = PAGE.read_text()
    if MARKER not in page:
        sys.exit("could not find the app's script tag — has the file structure changed?")
    OUT.write_text(page.replace(MARKER, HARNESS % SHIM.read_text() + MARKER))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
