#!/usr/bin/env python3
"""Generate _capture.html — the synth with a recorder on the master bus, for answering
"is this artefact actually in the audio we render?"

An AudioWorklet sits between master and ctx.destination, passes audio through untouched,
and keeps the last 10 seconds in a ring buffer. Two buttons appear over the UI:

    SAVE LAST 10s      writes the ring to a WAV in Downloads
    INJECT TEST CLICK  punches a 1.5ms hole in the master gain

    python3 tools/build-capture-harness.py    # then open _capture.html

The second button is the point of this tool, and the reason it works where several
cleverer attempts failed.

An earlier version tried to DETECT artefacts automatically, flagging any sample-to-sample
jump above a threshold. It was wrong three times over: it watched only channel 0 while
voices are panned across both, it read past its own ring buffer's write head and reported
the wrap as a discontinuity, and its threshold tracked nothing meaningful — in one run it
flagged 40 "discontinuities" in audio that was completely clean to the ear. Every one of
those produced a confident, wrong conclusion.

INJECT is the control. It puts a known artefact into the signal ABOVE the tap, so it MUST
appear in the recording. If the analysis finds the injected click and not the one being
chased, the artefact is provably not in the rendered audio — a conclusion that rests on a
validated instrument rather than on absence of evidence. Validate on the known-bad case
first; a detector that has never caught anything has not been shown to detect anything.

That is how the click hunt actually ended: injected clicks were found at signal-to-noise
of 20x the detection floor, while recordings saved immediately after real audible clicks
contained nothing at all. The artefact was below the graph entirely — see the click
investigation section in HANDOFF.md.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "patchwork-chord-synth.html"
OUT = ROOT / "_capture.html"

ANCHOR = "  comp.connect(master); master.connect(ctx.destination);"

INJECT = r"""
  /* ---- rolling recorder (diagnostic build only) ----
     Threshold detection failed: it flagged 40 "discontinuities" in a run with no audible
     click at all, because a chord attack and a click look the same over half a millisecond.
     So the ear is the detector now. This keeps the last 10 seconds of the master bus in a
     ring buffer; the button writes it to a WAV, which can be examined properly offline. */
  (function(){
    var WORKLET = `
      class CS1Tap extends AudioWorkletProcessor {
        constructor(){
          super();
          this.len = Math.ceil(sampleRate * 10);
          this.ring = [new Float32Array(this.len), new Float32Array(this.len)];
          this.w = 0; this.prev = [0, 0]; this.winMax = 0; this.winEnd = 0;
          this.port.onmessage = e => {
            if (!e.data || e.data.cmd !== 'dump') return;
            const L = this.ordered(0), R = this.ordered(1);
            this.port.postMessage({kind:'dump', rate:sampleRate, L:L, R:R}, [L.buffer, R.buffer]);
          };
        }
        ordered(c){
          const out = new Float32Array(this.len), r = this.ring[c];
          out.set(r.subarray(this.w), 0);
          out.set(r.subarray(0, this.w), this.len - this.w);
          return out;
        }
        process(inputs, outputs){
          const inp = inputs[0], out = outputs[0];
          if (!inp || !inp.length || !inp[0]) return true;
          for (let c = 0; c < out.length; c++){
            const s = inp[Math.min(c, inp.length - 1)];
            if (s) out[c].set(s);
          }
          const n = inp[0].length, len = this.len;
          let maxD = 0;
          for (let c = 0; c < Math.min(2, inp.length); c++){
            const ch = inp[c], r = this.ring[c];
            for (let i = 0; i < n; i++){
              const v = ch[i], d = Math.abs(v - this.prev[c]);
              if (d > maxD) maxD = d;
              this.prev[c] = v;
              r[(this.w + i) % len] = v;
            }
          }
          this.w = (this.w + n) % len;
          if (maxD > this.winMax) this.winMax = maxD;
          if (currentTime > this.winEnd){
            this.port.postMessage({kind:'win', t:currentTime, max:this.winMax});
            this.winMax = 0; this.winEnd = currentTime + 0.5;
          }
          return true;
        }
      }
      registerProcessor('cs1-tap', CS1Tap);
    `;

    function toWav(L, R, rate){
      var n = L.length, buf = new ArrayBuffer(44 + n * 4), v = new DataView(buf), p = 0;
      function str(s){ for (var i = 0; i < s.length; i++) v.setUint8(p++, s.charCodeAt(i)); }
      function u32(x){ v.setUint32(p, x, true); p += 4; }
      function u16(x){ v.setUint16(p, x, true); p += 2; }
      str('RIFF'); u32(36 + n * 4); str('WAVE'); str('fmt '); u32(16); u16(1); u16(2);
      u32(rate); u32(rate * 4); u16(4); u16(16); str('data'); u32(n * 4);
      for (var i = 0; i < n; i++){
        var l = Math.max(-1, Math.min(1, L[i])), r = Math.max(-1, Math.min(1, R[i]));
        v.setInt16(p, l * 32767, true); p += 2;
        v.setInt16(p, r * 32767, true); p += 2;
      }
      return new Blob([buf], {type:'audio/wav'});
    }

    var url = URL.createObjectURL(new Blob([WORKLET], {type:'application/javascript'}));
    ctx.audioWorklet.addModule(url).then(function(){
      var tap = new AudioWorkletNode(ctx, 'cs1-tap', {numberOfInputs:1, numberOfOutputs:1, outputChannelCount:[2]});
      master.disconnect();
      master.connect(tap);
      tap.connect(ctx.destination);

      var n = 0, windows = [];
      tap.port.onmessage = function(e){
        var m = e.data;
        if (m.kind === 'win'){ windows.push(m.max); if (windows.length > 600) windows.shift(); return; }
        n++;
        var a = document.createElement('a');
        a.href = URL.createObjectURL(toWav(m.L, m.R, m.rate));
        a.download = 'patchwork-click-' + n + '.wav';
        document.body.appendChild(a); a.click(); a.remove();
        btn.textContent = 'SAVED #' + n + ' — keep playing';
        setTimeout(function(){ btn.textContent = 'SAVE LAST 10s'; }, 2500);
      };

      var BTN = 'position:fixed;right:10px;z-index:99999;padding:14px 18px;'
        + 'font:600 13px/1 system-ui,sans-serif;letter-spacing:.08em;color:#fff;'
        + 'border:0;border-radius:8px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.4);';

      var btn = document.createElement('button');
      btn.textContent = 'SAVE LAST 10s';
      btn.style.cssText = BTN + 'top:10px;background:#d84a2f';
      btn.onclick = function(){ tap.port.postMessage({cmd:'dump'}); };
      document.body.appendChild(btn);

      /* Known-bad control. Punches a 1.5ms hole in the master gain: a real, audible click,
         deliberately placed ABOVE the tap so it must appear in the recording. If the
         analysis finds this one but not the clicks being chased, then those clicks are
         provably not in the rendered audio — and that conclusion rests on a validated
         instrument instead of on absence of evidence. */
      var inj = document.createElement('button');
      inj.textContent = 'INJECT TEST CLICK';
      inj.style.cssText = BTN + 'top:62px;background:#3a6ea5';
      inj.onclick = function(){
        var g = master.gain, t = ctx.currentTime + 0.05, v = g.value;
        g.setValueAtTime(v, t);
        g.setValueAtTime(0, t + 0.0004);
        g.setValueAtTime(v, t + 0.0019);
        window.__cap.injections.push(+t.toFixed(4));
        console.log('injected test click at ctx time', t.toFixed(4));
      };
      document.body.appendChild(inj);

      window.__cap = {
        injections: [],
        save: function(){ tap.port.postMessage({cmd:'dump'}); },
        levels: function(){
          var s = windows.slice().sort(function(a,b){ return a-b; });
          if (!s.length) return 'no data yet';
          return 'max jump per 0.5s — median ' + s[s.length>>1].toFixed(3)
            + '  p90 ' + s[Math.floor(s.length*0.9)].toFixed(3) + '  peak ' + s[s.length-1].toFixed(3);
        }
      };
      console.log('recorder ready — hit SAVE LAST 10s right after you hear a click');
    }).catch(function(err){ console.error('recorder failed to install:', err); });
  })();
"""


def main():
    if not APP.exists():
        sys.exit(f"missing {APP}")
    src = APP.read_text()
    if src.count(ANCHOR) != 1:
        sys.exit("anchor not found or not unique — the master chain in initAudio() changed")
    OUT.write_text(src.replace(ANCHOR, ANCHOR + "\n" + INJECT))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
