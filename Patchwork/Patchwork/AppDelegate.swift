import UIKit
import AVFoundation

/// Audio session handling, kept in one place because it has to be re-applied — iOS
/// deactivates the session on interruption, and a one-shot setup at launch leaves the app
/// silent afterwards with no way back short of relaunching.
enum AudioSession {

    static func configure() {
        let session = AVAudioSession.sharedInstance()
        do {
            // WebKit otherwise uses the "ambient" category, which the ring/silent switch
            // mutes. .playback keeps the synth audible regardless of the switch.
            try session.setCategory(.playback, mode: .default, options: [])
            // Ask for a short IO buffer. iOS grants what the hardware allows, but the
            // default is long enough to be audible as lag on a musical instrument.
            try session.setPreferredIOBufferDuration(0.005)
            try session.setActive(true)
        } catch {
            NSLog("[Patchwork] audio session setup failed: \(error)")
        }
    }

    static func reactivate() {
        do {
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            NSLog("[Patchwork] audio session reactivate failed: \(error)")
        }
    }
}

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {

        AudioSession.configure()

        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = WebHostViewController()
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}
