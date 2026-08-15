# Patchwork CS·1 — iOS wrapper

iOS has no Web MIDI. Every browser there is WebKit underneath, so no browser choice and no
"add to home screen" changes that. This wrapper hosts the existing synth in a `WKWebView`
and supplies the one API the platform is missing.

**The web app is not modified.** `midi-bridge.js` is injected as a user script before the
page runs, defining `navigator.requestMIDIAccess()` in terms of a native CoreMIDI bridge.
Everything above it — chord pads, MIDI learn, clock sync, panic, note scheduling — works
unchanged, and the same HTML still runs in a desktop browser with the shim inert.

## What the wrapper actually buys you

| | Browser on iOS | This wrapper |
| --- | --- | --- |
| MIDI in/out | none | full CoreMIDI |
| Silent switch | mutes everything | ignored (`.playback` session) |
| Audio over USB-C | works | works |
| Latency | WebKit's | WebKit's — unchanged |

Note the last row. This is still WebKit rendering and Web Audio doing the synthesis, so it
does **not** improve latency. If low latency is the goal, that needs a native audio engine,
which is a much larger job.

## Files

```
ios/
  midi-bridge.js               injected shim — implements the Web MIDI surface the app uses
  Sources/MIDIBridge.swift     CoreMIDI: device discovery, input, scheduled output
  Sources/WebHostViewController.swift   WKWebView host + JS bridge
  Sources/AppDelegate.swift    audio session + window
```

## Building it

Needs **full Xcode** from the App Store. Command Line Tools alone cannot build an iOS app.

1. Xcode → *New Project* → **iOS · App**, interface **Storyboard**, language **Swift**.
   Name it `Patchwork`.
2. Delete the generated `ViewController.swift`, `Main.storyboard`, and `SceneDelegate.swift`.
   In *Info.plist*, remove the `UIApplicationSceneManifest` entry and the
   "Main storyboard file base name" entry — `AppDelegate` creates the window itself.
3. Drag in the three files from `Sources/`.
4. Drag in `midi-bridge.js` **and** `patchwork-chord-synth.html` from the repo root, with
   *Copy items if needed* ticked and *Add to target* checked. Confirm both appear under
   *Build Phases → Copy Bundle Resources* — if they are missing the app will launch to a
   blank screen.
5. Set your team under *Signing & Capabilities* and run on a device.

The Simulator is fine for checking the UI loads, but it cannot see USB MIDI hardware — the
device list will be empty there. MIDI has to be tested on a real device.

## Connecting the EP-133

USB-C to USB-C. iOS enumerates class-compliant USB MIDI without a driver, exactly as macOS
does, so the device should appear in the app's MIDI **Input** and **Output** lists.

On older iPhones with Lightning you need a Camera Adapter, and one that supplies power if
the device draws any.

## The bridge contract

If you ever want to reimplement either side, this is the whole interface.

**JS → native**, via `window.webkit.messageHandlers.patchworkMIDI.postMessage`:

```js
{ op: "init" }                                      // request a device list
{ op: "send",  port: "<id>", bytes: [...], delayMs } // schedule bytes
{ op: "clear", port: "<id>" }                        // drop queued output
```

**native → JS**:

```js
window.__patchworkMIDI.onDevices([{ id, name, type: "input" | "output" }])
window.__patchworkMIDI.onMessage("<portId>", [bytes])
```

`delayMs` matters. The sequencer schedules ahead — measured up to ~2.8 seconds for long
chords — and the shim converts Web MIDI's absolute timestamps into a delay so CoreMIDI can
place the packet itself. Re-timing those in a JavaScript timer would throw away the
accuracy the lookahead scheduler exists to provide.

## Known limitation to watch

Incoming MIDI is delivered to the page with one `evaluateJavaScript` call per message. At
120 bpm, MIDI clock alone is 48 messages a second, plus notes. That is likely fine, but if
clock sync turns out jittery on hardware, the fix is to batch messages into a small array
and flush on a timer or a `CADisplayLink` rather than calling across the bridge per message.

I have not been able to test that — it needs the real device.
