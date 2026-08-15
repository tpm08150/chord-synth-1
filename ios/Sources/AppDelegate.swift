import UIKit
import AVFoundation

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {

        // The reason the web version is silent when the ring/silent switch is on: WebKit
        // uses the "ambient" audio session, which the hardware switch mutes. A native host
        // can choose "playback" instead, so the app keeps sounding regardless — one of the
        // few things the wrapper genuinely fixes beyond MIDI.
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [])
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            NSLog("Audio session setup failed: \(error)")
        }

        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = WebHostViewController()
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}
