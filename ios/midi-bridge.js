// Web MIDI shim backed by CoreMIDI.
//
// Injected by the iOS host as a WKUserScript at document start, so the synth itself needs
// no changes at all — it goes on calling navigator.requestMIDIAccess() and never learns
// there is a native layer underneath.
//
// Installs ONLY when the native bridge is present, so loading the same HTML in a desktop
// browser is completely unaffected.
//
// JS  -> native : window.webkit.messageHandlers.patchworkMIDI.postMessage({op, ...})
//   {op:"init"}
//   {op:"send",  port:<id>, bytes:[...], delayMs:<number>}
//   {op:"clear", port:<id>}
//
// native -> JS  : window.__patchworkMIDI.*
//   onDevices([{id, name, type:"input"|"output"}])
//   onMessage(portId, [bytes])

(function () {
  "use strict";

  var bridge = window.webkit
    && window.webkit.messageHandlers
    && window.webkit.messageHandlers.patchworkMIDI;
  if (!bridge) return;                       // plain web build — leave everything alone
  if (navigator.requestMIDIAccess) return;   // never shadow a real implementation

  var inputs = new Map();
  var outputs = new Map();
  var access = null;
  var gotFirstList = false;
  var pendingResolvers = [];

  function Port(info, type) {
    this.id = String(info.id);
    this.name = info.name || String(info.id);
    this.manufacturer = info.manufacturer || "";
    this.version = "";
    this.type = type;
    this.state = "connected";
    this.connection = "open";
    this.onmidimessage = null;
    this.onstatechange = null;
  }
  Port.prototype.open = function () { return Promise.resolve(this); };
  Port.prototype.close = function () { return Promise.resolve(this); };
  Port.prototype.addEventListener = function () {};
  Port.prototype.removeEventListener = function () {};

  function Input(info) { Port.call(this, info, "input"); }
  Input.prototype = Object.create(Port.prototype);
  Input.prototype.constructor = Input;

  function Output(info) { Port.call(this, info, "output"); }
  Output.prototype = Object.create(Port.prototype);
  Output.prototype.constructor = Output;

  // Web MIDI timestamps are absolute, in the performance.now() domain. CoreMIDI wants a
  // schedule time, so convert to a delay here and let the native side place it precisely —
  // doing the waiting in JS with setTimeout would throw away the timing accuracy the
  // sequencer's lookahead depends on.
  Output.prototype.send = function (data, timestamp) {
    var bytes = Array.prototype.slice.call(data);
    var delay = 0;
    if (typeof timestamp === "number" && isFinite(timestamp) && timestamp > 0) {
      delay = Math.max(0, timestamp - performance.now());
    }
    bridge.postMessage({ op: "send", port: this.id, bytes: bytes, delayMs: delay });
  };
  Output.prototype.clear = function () {
    bridge.postMessage({ op: "clear", port: this.id });
  };

  function MIDIAccess() {
    this.inputs = inputs;
    this.outputs = outputs;
    this.sysexEnabled = false;
    this.onstatechange = null;
  }
  MIDIAccess.prototype.addEventListener = function () {};
  MIDIAccess.prototype.removeEventListener = function () {};

  function fire(port) {
    if (!access || typeof access.onstatechange !== "function") return;
    try { access.onstatechange({ port: port, target: access }); } catch (e) {}
  }

  window.__patchworkMIDI = {
    // Rebuild the port maps, keeping the existing objects for devices that are still
    // present — the app stores a reference to the bound input, and swapping the object
    // out from under it would silently drop its onmidimessage handler.
    onDevices: function (list) {
      var seenIn = {}, seenOut = {}, changed = false, i, info, port;
      list = list || [];
      for (i = 0; i < list.length; i++) {
        info = list[i];
        var id = String(info.id);
        if (info.type === "input") {
          seenIn[id] = true;
          if (!inputs.has(id)) { inputs.set(id, new Input(info)); changed = true; }
          else { inputs.get(id).name = info.name || id; }
        } else {
          seenOut[id] = true;
          if (!outputs.has(id)) { outputs.set(id, new Output(info)); changed = true; }
          else { outputs.get(id).name = info.name || id; }
        }
      }
      inputs.forEach(function (p, id) {
        if (!seenIn[id]) { p.state = "disconnected"; inputs.delete(id); changed = true; port = p; }
      });
      outputs.forEach(function (p, id) {
        if (!seenOut[id]) { p.state = "disconnected"; outputs.delete(id); changed = true; port = p; }
      });

      if (!gotFirstList) {
        gotFirstList = true;
        var rs = pendingResolvers; pendingResolvers = [];
        for (i = 0; i < rs.length; i++) rs[i]();
      }
      // Fire regardless of whether this was the first list. If the 500ms wait already
      // timed out, requestMIDIAccess resolved with empty maps and onstatechange is the
      // only thing that will ever tell the app a device showed up.
      if (changed) fire(port || null);
    },

    onMessage: function (portId, bytes) {
      var p = inputs.get(String(portId));
      if (!p || typeof p.onmidimessage !== "function") return;
      try {
        p.onmidimessage({
          data: new Uint8Array(bytes),
          receivedTime: performance.now(),
          target: p
        });
      } catch (e) {}
    }
  };

  navigator.requestMIDIAccess = function () {
    if (!access) access = new MIDIAccess();
    bridge.postMessage({ op: "init" });
    if (gotFirstList) return Promise.resolve(access);
    // Wait briefly for the first device list so the app's "auto-select the first input"
    // has something to pick, but never hang if nothing is plugged in.
    return new Promise(function (resolve) {
      var done = false;
      function finish() { if (!done) { done = true; resolve(access); } }
      pendingResolvers.push(finish);
      setTimeout(finish, 500);
    });
  };
})();
