# Patchwork CS·1

A chord synthesizer that runs entirely in the browser. One HTML file, no build step, no
dependencies — generate chord progressions, shape them with a small synth engine, and drive
external hardware over MIDI.

## What it does

**Progressions.** Eleven moods, each a pool of hand-written templates with a distinct
harmonic identity — Lydian, Dorian, gospel, quartal, minor jazz and so on. Pick a key, force
major or minor, and choose 3–12 chords. Chord names are spelled by scale degree rather than
from a lookup table, so a borrowed ♭VII in C reads `B♭` and not `A♯`.

**Pads.** Chords are laid out three across, filled bottom-up, so pad 1 sits bottom-left and
the grid mirrors a 3×4 hardware pad layout. Each pad can be edited independently — any root,
any of 16 chord types, and a length from ¼ bar to 8 bars in quarter-bar steps.

**Sound.** Eight voices, including custom wavetables, bandpass and highpass designs. Six
faders (tone, attack, release, space, spread, level) that move under sounding notes rather
than waiting for the next one. Four motions: hold, strum, arpeggiator and a step-sequenced
pulse, with swing for the stepped ones.

**MIDI.** Chord pads and clock sync in, note events out, mirroring the internal engine so the
two can't drift. MIDI learn maps hardware pads to chord slots and hardware knobs to faders.
A panic button sends all-notes-off on every channel.

**Audio I/O.** Route output to a USB interface and take input back in, with a level meter
that reads straight off the input so you can confirm signal without monitoring it into a
feedback loop.

**Patches.** Save and load named setups in the browser, or export and import them as JSON.

## Running it

Web MIDI requires a secure context, so `file://` will not work — it needs `localhost` or
HTTPS. There is a tiny no-cache dev server included:

```bash
python3 serve.py
```

Then open <http://localhost:8123/patchwork-chord-synth.html>.

Deployed on Netlify it is served over HTTPS, which satisfies the secure-context requirement
with no extra setup.

## Browser support

Chrome or Edge are the target. Both of the hardware-facing features are Chromium-first:

| Feature | Requirement |
| --- | --- |
| Web MIDI | Chrome, Edge, Safari 18+. Firefox prompts for permission. |
| `AudioContext.setSinkId` (output device routing) | Chrome 110+ |

Everything else — progression generation, the synth engine, patches — works in any modern
browser. The app degrades with an explanatory message rather than breaking when MIDI is
unavailable.

## Hardware notes

Built against a Teenage Engineering EP-133. It enumerates as a class-compliant USB audio
device (2 in / 2 out at 44.1 kHz) and a USB MIDI device, so macOS picks it up with no driver
and the browser can reach both directly.

Latency is the one real limitation of staying in the browser: Chrome's output latency runs
roughly 15–40 ms and is not tunable. Fine for sequencing and recording, less so for tight
live playing against an external clock. The stats line under Audio I/O reports the actual
figure for your device.
