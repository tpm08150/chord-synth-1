# Patchwork CS·1 — handoff

Context for picking this up cold. Everything below is verified unless it says otherwise.

- **Repo** <https://github.com/tpm08150/chord-synth-1>
- **Live** <https://chord-synth-1.netlify.app/> (auto-deploys on push to `main`)
- **Hardware** Teenage Engineering EP-133 (MIDI in + clock, class-compliant USB audio),
  EP-136 mixer fed from the synth's audio out. Mac + iPhone 17 Pro (iOS 26.5.1).

## What it is

A chord synthesizer that generates progressions, plays them through a small Web Audio
engine, and drives external hardware over MIDI. **The whole web app is one file** —
`patchwork-chord-synth.html`, ~2800 lines, no build step, no dependencies. An iOS wrapper
hosts that same file unmodified and supplies the one API iOS lacks.

## Layout

```
patchwork-chord-synth.html   the entire web app
serve.py                     dev server that disables caching (see gotchas)
netlify.toml                 publish from root, rewrite / to the html, no-store on html
ios/
  midi-bridge.js             Web MIDI shim over a native bridge, injected at document start
  Sources/*.swift            canonical Swift; copied into Patchwork/Patchwork/ when changed
  build-test-harness.py      generates _iostest.html — the app + a mocked native side
  README.md                  bridge contract and Xcode setup
Patchwork/                   the Xcode project (Xcode 16 synchronized groups)
```

`ios/Sources/*.swift` and `Patchwork/Patchwork/*.swift` are duplicates — **edit `ios/Sources`
and copy across**, or they drift. The two web resources are *not* duplicated: a build phase
copies them from the repo root into the bundle on every build.

## Running it

```bash
python3 serve.py                  # http://localhost:8123/patchwork-chord-synth.html
python3 ios/build-test-harness.py # then open _iostest.html to test MIDI without hardware
```

Web MIDI needs a secure context, so `file://` will not work — localhost or the Netlify URL.
iOS builds need full Xcode (26.x for this device) and run to the phone from Xcode.

## Web app map

| Area | Where |
| --- | --- |
| Chord theory, spelling | `QUAL`, `POOLS`, `DIATONIC`, `rootName()`, `makeProgression()` |
| Synth voices | `VOICES` (12), `PERIODIC_SPEC` for wavetables |
| Note scheduling | `chordEvents()` — single source of truth for engine *and* MIDI out |
| Envelopes | `trigger()` |
| Transport | `tick()` — 25ms interval, 200ms lookahead |
| Held MIDI pads | `padTick()` — separate scheduler for pads held down |
| Params | `P` (faders), `state`, `MIDI`, `ARP`, `PULSE`, `BASSQ`, `SW`, `SYNC` |
| Patches | `snapshot()` / `restore()`, `PATCH_VERSION`, `TONE_RANGES` |

### Design decisions worth not undoing

- **`chordEvents()` builds one event list** consumed by both the internal engine and MIDI
  out, so the two cannot drift apart. Anything that changes what's played goes there.
- **Chord names are spelled from scale degree**, not a chromatic lookup — that's the only
  way `♭VII` in C reads as `B♭` rather than `A♯`. A lookup table cannot spell borrowed
  chords no matter how the key signature is chosen.
- **Pads fill bottom-up** via explicit `grid-row`/`grid-column`, so document order stays
  `1..n` and `paint()`, `flashPad()` and the pad badges all index into it correctly.
  Do not "simplify" this by reversing the DOM.
- **Patterns repeat over longer pads rather than stretching.** A 2-bar pad plays the
  8-step pattern twice at the same speed.
- **`bpmExact` drives the transport; `state.bpm` is display only.** Deriving bar length
  from a rounded tempo caused ~180ms/min of drift against external clock.
- **Horizontal faders register in `faderCtl`** exactly like the vertical bank, so they get
  MIDI learn, patch save and CC control for free.

## iOS wrapper

The web app is **not modified** for iOS. `midi-bridge.js` is injected as a `WKUserScript`
at document start and defines `navigator.requestMIDIAccess()` over CoreMIDI. It declines to
install when a real implementation exists, so the same file still runs in a desktop browser.

Bridge contract (also in `ios/README.md`):

```js
// JS -> native, via window.webkit.messageHandlers.patchworkMIDI.postMessage
{op:"init"} | {op:"send", port, bytes, delayMs} | {op:"clear", port}
// native -> JS
window.__patchworkMIDI.onDevices([{id,name,type}])
window.__patchworkMIDI.onMessage(portId, [bytes])
```

`delayMs` matters: the sequencer schedules up to ~2.8s ahead, and the shim converts Web
MIDI's absolute timestamps to a delay so CoreMIDI places the packet. Re-timing those in a
JS timer would throw away the lookahead's accuracy.

The wrapper also fixes two things beyond MIDI: an `AVAudioSession` `.playback` category so
the ring/silent switch doesn't mute it, and a 5ms preferred IO buffer — the phone reports
**1.8ms output latency**, far better than desktop's ~32ms.

## Gotchas that cost real time

- **iOS has no Web MIDI, in any browser.** All iOS browsers are WebKit. A PWA doesn't
  change it. That's the entire reason the wrapper exists.
- **The ring/silent switch mutes WebKit audio** in the browser. Cost an hour of
  misdiagnosis. The native wrapper is immune.
- **Xcode's script sandbox** (`ENABLE_USER_SCRIPT_SANDBOXING = YES`) denies writes a run
  script hasn't declared. Verifying with `-derivedDataPath /tmp` hides this because /tmp is
  permitted — always verify against the default DerivedData location.
- **Browsers cache the local dev page aggressively.** `serve.py` sends `no-store`; plain
  `python3 -m http.server` does not, and will serve a stale page after edits.
- **`localStorage` is per-origin and per-device**, so patches don't move between localhost,
  Netlify and the phone. Export/import JSON to carry them.
- The Claude Code Browser pane runs **hidden**, so `requestAnimationFrame` never fires
  there — anything rAF-driven can't be verified by DOM polling alone, only by screenshot.

## State of play

Working and tested on hardware: MIDI in with chord pads, clock follow, MIDI out, panic,
audio to the EP-133/EP-136, the iOS app on the phone, background/foreground recovery.

**Verified only synthetically** (no hardware in the loop):
- CoreMIDI device discovery beyond "it found the EP-133" — deeper paths are untested
- MIDI learn on the phone
- Clock drift over long takes; measured 54ms/min in a test rig whose own jitter accounts
  for most of that

**Known limitation, deliberately left:** the transport *follows* clock tempo rather than
phase-locking to it, so residual tempo error accumulates instead of being corrected. The
Offset control compensates the constant part. If long takes creep, the fix is continuous
phase correction against the pulse count — a real change, worth doing with measurements
rather than pre-emptively.

**Also unproven:** incoming MIDI crosses the bridge one `evaluateJavaScript` call per
message. Clock alone is ~48/sec at 120bpm. If sync turns out jittery on hardware, batching
into an array flushed on a timer is the fix.

## Working style that suited this project

Measure rather than assume — most of the real bugs here were found by rendering audio
offline in an `OfflineAudioContext` and checking dB/RMS, or by capturing scheduled
oscillator times, not by listening. Several "fixes" were wrong until measured: the Space
fader was inaudible at −23dB, `brass` was +3.3dB too loud, Tone's bottom end did nothing
at −0.7dB, and the first bass "decay" was indistinguishable from sustain.

Test harnesses that paid for themselves: `ios/build-test-harness.py` (mocked native MIDI),
and patching `AudioContext.prototype.createOscillator` to capture scheduled note times.
