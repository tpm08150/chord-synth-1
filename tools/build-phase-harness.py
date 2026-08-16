#!/usr/bin/env python3
"""Generate _phasetest.html — the synth plus a synthetic MIDI clock and an independent
drift measurement.

Same trick as ios/build-test-harness.py: the app is untouched, and everything it needs is
supplied from outside. Here that means a fake Web MIDI input emitting 24ppqn clock, plus a
patched AudioContext that records when oscillators are actually scheduled.

The recorded oscillator times are the point. The app's own phase readout is the thing under
test, so trusting it to report its own accuracy would be circular — chord onsets are ground
truth, measured on the audio clock, against clock pulses measured on the wall clock. The
gap between those two is exactly the drift the phase loop exists to remove.

    python3 tools/build-phase-harness.py && open _phasetest.html
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "patchwork-chord-synth.html"
OUT = ROOT / "_phasetest.html"

HARNESS = r"""
<script>
/* ---- test rig: runs BEFORE the app, so the app finds all of this already in place ---- */
(() => {
"use strict";
const R = window.__phase = {
  pulses: [],        // perf-domain emission times of every 0xF8 we sent
  starts: [],        // ctx-domain oscillator start times the app scheduled
  ctx: null,
  bpm: 120,
  running: false,
  stepPhase: 0       // ms of deliberate phase step, for testing pull-in
};

/* capture the app's AudioContext and every note it schedules */
const AC = window.AudioContext || window.webkitAudioContext;
const wrap = function(...a){
  const c = new AC(...a);
  if (!R.ctx) R.ctx = c;
  const co = c.createOscillator.bind(c);
  c.createOscillator = function(){
    const o = co();
    const st = o.start.bind(o);
    o.start = function(t){ R.starts.push(t == null ? c.currentTime : t); return st(t); };
    return o;
  };
  return c;
};
wrap.prototype = AC.prototype;
window.AudioContext = window.webkitAudioContext = wrap;

/* ---- fake Web MIDI: one input that emits clock, one output that swallows it ---- */
function Port(id, name, type){
  this.id = id; this.name = name; this.manufacturer = "test"; this.type = type;
  this.state = "connected"; this.connection = "open"; this.onmidimessage = null;
}
Port.prototype.open = function(){ return Promise.resolve(this); };
Port.prototype.close = function(){ return Promise.resolve(this); };
Port.prototype.addEventListener = function(){};
Port.prototype.removeEventListener = function(){};
Port.prototype.send = function(){};
Port.prototype.clear = function(){};

const input = new Port("test-in", "Test Clock", "input");
const access = {
  inputs: new Map([["test-in", input]]),
  outputs: new Map([["test-out", new Port("test-out", "Test Sink", "output")]]),
  sysexEnabled: false,
  onstatechange: null,
  addEventListener(){}, removeEventListener(){}
};
navigator.requestMIDIAccess = () => Promise.resolve(access);

/* ---- the clock itself ----
   Scheduled against an absolute origin rather than by repeated setTimeout(interval), so the
   generator's own error can't masquerade as the app's. Every pulse's emission time is
   recorded, so even if the browser throttles the timer the measurement stays honest. */
let origin = 0, n = 0, timer = null;
function pump(){
  const per = 60000 / R.bpm / 24;
  const now = performance.now();
  while (origin + n * per + R.stepPhase <= now){
    const t = performance.now();
    R.pulses.push(t);
    if (input.onmidimessage) input.onmidimessage({data:new Uint8Array([0xF8]), receivedTime:t, target:input});
    n++;
  }
  timer = setTimeout(pump, 2);
}
R.start = bpm => {
  if (R.running) return;
  R.bpm = bpm || R.bpm; R.running = true;
  origin = performance.now(); n = 0;
  pump();
};
R.stop = () => { R.running = false; clearTimeout(timer); timer = null; };
/* shove the clock grid sideways, to watch the loop pull a step error back in */
R.step = ms => { R.stepPhase += ms; };

/* ---- analysis ----
   Oscillator starts arrive several per chord (chord tones plus the bass hit). Cluster them
   and keep the first of each: that is the bar line on the audio clock. */
R.bars = (tol = .05) => {
  const s = R.starts.slice().sort((a, b) => a - b);
  const out = [];
  for (const t of s) if (!out.length || t - out[out.length - 1] > tol) out.push(t);
  return out;
};
/* Elapsed time between bar N and bar 0 on the audio clock, minus the same span on the clock
   we sent — in ms. Slope of this is the drift; a constant is just latency and offset. */
R.drift = () => {
  const bars = R.bars();
  if (bars.length < 3 || R.pulses.length < 96) return null;
  const perBar = 96, out = [];
  for (let i = 1; i < bars.length; i++){
    const p = i * perBar;
    if (p >= R.pulses.length) break;
    const audioMs = (bars[i] - bars[0]) * 1000;
    const clockMs = R.pulses[p] - R.pulses[0];
    out.push({bar:i, ms:+(audioMs - clockMs).toFixed(2), atMin:+((clockMs / 60000).toFixed(3))});
  }
  return out;
};
/* least-squares slope of that, in ms per minute */
R.slope = () => {
  const d = R.drift();
  if (!d || d.length < 4) return null;
  const n = d.length;
  const mx = d.reduce((s, p) => s + p.atMin, 0) / n;
  const my = d.reduce((s, p) => s + p.ms, 0) / n;
  let num = 0, den = 0;
  for (const p of d){ num += (p.atMin - mx) * (p.ms - my); den += (p.atMin - mx) ** 2; }
  return den ? +(num / den).toFixed(1) : null;
};
R.reset = () => { R.starts.length = 0; R.pulses.length = 0; origin = performance.now(); n = 0; };
})();
</script>
"""


def main():
    if not APP.exists():
        sys.exit(f"missing {APP}")
    html = APP.read_text()
    marker = "<script>"
    i = html.index(marker)
    OUT.write_text(html[:i] + HARNESS + html[i:])
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(html):,} -> {OUT.stat().st_size:,} bytes)")
    print("  __phase.start(120) / .step(ms) / .slope() / .drift() / .reset()")


if __name__ == "__main__":
    main()
