import UIKit
import WebKit
import AVFoundation

/// Hosts the synth's HTML in a WKWebView and wires `midi-bridge.js` to CoreMIDI.
///
/// The web app is loaded unmodified. The shim is injected as a user script at document
/// start, so `navigator.requestMIDIAccess` exists before any of the app's own code runs.
final class WebHostViewController: UIViewController, WKScriptMessageHandler, WKNavigationDelegate {

    private var webView: WKWebView!
    private let midi = MIDIBridge()
    private var bridgeReady = false
    private var pendingDevices: [MIDIDeviceInfo]?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.08, green: 0.09, blue: 0.10, alpha: 1)

        let controller = WKUserContentController()
        controller.add(self, name: "patchworkMIDI")

        if let url = Bundle.main.url(forResource: "midi-bridge", withExtension: "js"),
           let source = try? String(contentsOf: url, encoding: .utf8) {
            controller.addUserScript(WKUserScript(source: source,
                                                  injectionTime: .atDocumentStart,
                                                  forMainFrameOnly: true))
        } else {
            assertionFailure("midi-bridge.js is missing from the bundle")
        }

        let config = WKWebViewConfiguration()
        config.userContentController = controller
        config.allowsInlineMediaPlayback = true
        // Web Audio still needs a user gesture to start; this only stops WebKit demanding
        // one for <audio>/<video> elements.
        config.mediaTypesRequiringUserActionForPlayback = []

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.scrollView.bounces = false
        webView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: view.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])

        midi.onDevices = { [weak self] devices in
            guard let self else { return }
            guard self.bridgeReady else { self.pendingDevices = devices; return }
            self.pushDevices(devices)
        }
        midi.onMessage = { [weak self] id, bytes in
            self?.pushMessage(portID: id, bytes: bytes)
        }
        midi.start()

        // Coming back from another app: the session may have been deactivated and MIDI
        // connections dropped, and the page's AudioContext left suspended. None of that
        // recovers on its own — without this the app is silent until it's relaunched.
        NotificationCenter.default.addObserver(
            self, selector: #selector(appBecameActive),
            name: UIApplication.didBecomeActiveNotification, object: nil)
        NotificationCenter.default.addObserver(
            self, selector: #selector(audioInterrupted(_:)),
            name: AVAudioSession.interruptionNotification, object: nil)

        guard let page = Bundle.main.url(forResource: "patchwork-chord-synth", withExtension: "html") else {
            assertionFailure("patchwork-chord-synth.html is missing from the bundle")
            return
        }
        webView.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent())
    }

    // MARK: - lifecycle

    @objc private func appBecameActive() {
        AudioSession.reactivate()
        midi.refresh()                    // re-enumerate; endpoints may have changed while away
        resumeWebAudio()
    }

    @objc private func audioInterrupted(_ note: Notification) {
        guard let info = note.userInfo,
              let raw = info[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        if type == .ended {
            AudioSession.reactivate()
            resumeWebAudio()
        }
    }

    /// Nudge the page's AudioContext. iOS leaves it "interrupted" after a call or an app
    /// switch, and WebKit does not restore it by itself.
    private func resumeWebAudio() {
        eval("window.__patchworkResume && window.__patchworkResume();")
    }

    deinit { NotificationCenter.default.removeObserver(self) }

    // MARK: - JS -> native

    func userContentController(_ controller: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let op = body["op"] as? String else { return }

        switch op {
        case "init":
            midi.refresh()

        case "send":
            guard let port = body["port"] as? String,
                  let raw = body["bytes"] as? [Any] else { return }
            let bytes = raw.compactMap { ($0 as? NSNumber)?.uint8Value }
            let delay = (body["delayMs"] as? NSNumber)?.doubleValue ?? 0
            midi.send(portID: port, bytes: bytes, delayMs: delay)

        case "clear":
            if let port = body["port"] as? String { midi.clear(portID: port) }

        default:
            break
        }
    }

    // MARK: - native -> JS

    private func pushDevices(_ devices: [MIDIDeviceInfo]) {
        let payload = devices.map { ["id": $0.id, "name": $0.name, "type": $0.type] }
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else { return }
        eval("window.__patchworkMIDI && window.__patchworkMIDI.onDevices(\(json));")
    }

    private func pushMessage(portID: String, bytes: [UInt8]) {
        let list = bytes.map(String.init).joined(separator: ",")
        let id = portID.replacingOccurrences(of: "\"", with: "")
        eval("window.__patchworkMIDI && window.__patchworkMIDI.onMessage(\"\(id)\",[\(list)]);")
    }

    private func eval(_ js: String) {
        if Thread.isMainThread { webView.evaluateJavaScript(js, completionHandler: nil) }
        else { DispatchQueue.main.async { self.webView.evaluateJavaScript(js, completionHandler: nil) } }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        bridgeReady = true
        if let devices = pendingDevices { pushDevices(devices); pendingDevices = nil }
        else { midi.refresh() }
    }
}
