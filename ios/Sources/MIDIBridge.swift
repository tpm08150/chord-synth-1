import Foundation
import CoreMIDI

/// CoreMIDI wrapper exposed to the web layer by `midi-bridge.js`.
///
/// The web app schedules notes ahead of time — up to a few seconds for long chords — so
/// sends carry a delay in milliseconds rather than being fired immediately. That delay is
/// converted to a CoreMIDI timestamp so the packet is placed precisely, instead of being
/// re-timed by a JavaScript timer.
struct MIDIDeviceInfo {
    let id: String
    let name: String
    let type: String        // "input" | "output"
}

final class MIDIBridge {

    var onDevices: (([MIDIDeviceInfo]) -> Void)?
    var onMessage: ((String, [UInt8]) -> Void)?

    private var client = MIDIClientRef()
    private var inputPort = MIDIPortRef()
    private var outputPort = MIDIPortRef()

    private var sources: [String: MIDIEndpointRef] = [:]
    private var destinations: [String: MIDIEndpointRef] = [:]
    private var tokenToID: [Int: String] = [:]
    private var nextToken = 1

    private var timebase = mach_timebase_info_data_t()

    init() { mach_timebase_info(&timebase) }

    // MARK: - lifecycle

    func start() {
        MIDIClientCreateWithBlock("PatchworkCS1" as CFString, &client) { [weak self] _ in
            // Any setup change — device plugged, unplugged, renamed
            DispatchQueue.main.async { self?.refresh() }
        }

        MIDIInputPortCreateWithBlock(client, "PatchworkIn" as CFString, &inputPort) { [weak self] listPtr, refCon in
            guard let self else { return }
            let token = refCon.map { Int(bitPattern: $0) } ?? 0
            guard let id = self.tokenToID[token] else { return }

            var packet = listPtr.pointee.packet
            for _ in 0 ..< listPtr.pointee.numPackets {
                let count = Int(packet.length)
                let bytes: [UInt8] = withUnsafeBytes(of: packet.data) { raw in
                    (0 ..< count).map { raw[$0] }
                }
                if !bytes.isEmpty {
                    DispatchQueue.main.async { self.onMessage?(id, bytes) }
                }
                packet = MIDIPacketNext(&packet).pointee
            }
        }

        MIDIOutputPortCreate(client, "PatchworkOut" as CFString, &outputPort)
        refresh()
    }

    // MARK: - devices

    func refresh() {
        var found: [MIDIDeviceInfo] = []

        // sources (things that send us MIDI)
        var newSources: [String: MIDIEndpointRef] = [:]
        for i in 0 ..< MIDIGetNumberOfSources() {
            let ep = MIDIGetSource(i)
            guard ep != 0 else { continue }
            let id = uniqueID(of: ep)
            newSources[id] = ep
            found.append(MIDIDeviceInfo(id: id, name: displayName(of: ep), type: "input"))

            if sources[id] == nil {                 // newly appeared — connect it
                let token = nextToken; nextToken += 1
                tokenToID[token] = id
                MIDIPortConnectSource(inputPort, ep, UnsafeMutableRawPointer(bitPattern: token))
            }
        }
        for (id, ep) in sources where newSources[id] == nil {
            MIDIPortDisconnectSource(inputPort, ep)
        }
        sources = newSources

        // destinations (things we send MIDI to)
        var newDestinations: [String: MIDIEndpointRef] = [:]
        for i in 0 ..< MIDIGetNumberOfDestinations() {
            let ep = MIDIGetDestination(i)
            guard ep != 0 else { continue }
            let id = uniqueID(of: ep)
            newDestinations[id] = ep
            found.append(MIDIDeviceInfo(id: id, name: displayName(of: ep), type: "output"))
        }
        destinations = newDestinations

        onDevices?(found)
    }

    // MARK: - output

    func send(portID: String, bytes: [UInt8], delayMs: Double) {
        guard let dest = destinations[portID], !bytes.isEmpty else { return }

        // 0 means "as soon as possible" to CoreMIDI
        let timestamp: MIDITimeStamp = delayMs <= 0
            ? 0
            : mach_absolute_time() + nanosToAbs(UInt64(delayMs * 1_000_000))

        var storage = [UInt8](repeating: 0, count: 1024)
        storage.withUnsafeMutableBytes { raw in
            guard let base = raw.baseAddress else { return }
            let list = base.assumingMemoryBound(to: MIDIPacketList.self)
            var packet = MIDIPacketListInit(list)
            // MIDIPacketListAdd returns a non-optional pointer in Swift, so there is
            // nothing to nil-check — the buffer is fixed at 1024 and messages are 3 bytes.
            packet = MIDIPacketListAdd(list, 1024, packet, timestamp, bytes.count, bytes)
            _ = packet
            MIDISend(outputPort, dest, list)
        }
    }

    /// Drop anything queued but not yet delivered — the web layer calls this on Stop and
    /// Panic before sending all-notes-off, so scheduled notes can't fire afterwards.
    func clear(portID: String) {
        guard let dest = destinations[portID] else { return }
        MIDIFlushOutput(dest)
    }

    // MARK: - helpers

    private func nanosToAbs(_ nanos: UInt64) -> UInt64 {
        guard timebase.numer != 0 else { return nanos }
        return nanos * UInt64(timebase.denom) / UInt64(timebase.numer)
    }

    private func uniqueID(of ep: MIDIEndpointRef) -> String {
        var uid: Int32 = 0
        if MIDIObjectGetIntegerProperty(ep, kMIDIPropertyUniqueID, &uid) == noErr {
            return String(uid)
        }
        return "ep-\(ep)"
    }

    private func displayName(of ep: MIDIEndpointRef) -> String {
        var name: Unmanaged<CFString>?
        if MIDIObjectGetStringProperty(ep, kMIDIPropertyDisplayName, &name) == noErr,
           let value = name?.takeRetainedValue() {
            return value as String
        }
        return "MIDI \(ep)"
    }
}
