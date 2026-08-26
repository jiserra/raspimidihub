# RaspiMIDIHub USB Audio Routing Implementation Plan

## Implementation Progress

**Last Updated:** 2026-08-25  
**Current Phase:** Phase 2 - Audio Engine Core 🔄  
**Status:** ✅ Phase 1 Complete | ✅ Dynamic Mode Switching Complete | 🔄 Phase 2 In Progress

### Completed Tasks

#### ✅ Phase 1.1: Configuration Schema Update (2026-08-25)
- ✅ Added `operating_mode` field to DEFAULT_CONFIG ("midi" or "audio")
- ✅ Added `mode_locked` field to prevent accidental mode switching
- ✅ Added `audio_routing` section to DEFAULT_CONFIG with connections, devices, and global_settings
- ✅ Added Config class properties: `operating_mode`, `mode_locked`, `audio_routing`
- ✅ Added Config class methods: `set_operating_mode()`, `set_mode_locked()`, `set_audio_connections()`, `set_audio_devices()`

**Files Modified:**
- `src/raspimidihub/config.py` (Lines 157-225: DEFAULT_CONFIG update, Lines 266-293: Config properties, Lines 716-735: Config methods)

#### ✅ Phase 1.2: Mode Selection UI (2026-08-25)
- ✅ Added "Operating Mode" section to SECTIONS array in settings.js
- ✅ Created SettingsMode component with radio button interface
- ✅ Implemented mode switching confirmation dialog (no restart required)
- ✅ Added mode lock toggle to prevent accidental changes
- ✅ Added current mode status display (Active/Inactive indicators)
- ✅ Integrated SettingsMode into SettingsPage switch statement

**Files Modified:**
- `src/raspimidihub/static/pages/settings.js` (Lines 976-1092: SettingsMode component, Lines 1560-1571: SECTIONS array update, Line 1582: Switch case addition)

#### ✅ Phase 1.3: Startup Mode Detection (2026-08-25)
- ✅ Updated main startup logic in `__main__.py` to read operating_mode from config
- ✅ Implemented conditional engine initialization via EngineManager
- ✅ Added mode-specific logging ("Operating mode: MIDI/AUDIO")

**Files Modified:**
- `src/raspimidihub/__main__.py` (Lines 82-113: EngineManager integration)

#### ✅ Dynamic Mode Switching Implementation (2026-08-25)
- ✅ Created `EngineManager` class for dynamic engine switching
- ✅ Implemented clean engine shutdown and startup procedures
- ✅ Updated API endpoints to support mode switching without restart
- ✅ Updated UI to remove restart requirements
- ✅ Implemented engine factory pattern for creating appropriate engines
- ✅ Updated cleanup code to use EngineManager.shutdown()

**Files Created:**
- `src/raspimidihub/engine_manager.py` (Complete engine management system)

**Files Modified:**
- `src/raspimidihub/api.py` (Lines 336-349: register_api signature, Lines 605-648: PATCH /api/system mode switching)
- `src/raspimidihub/__main__.py` (Lines 96-113: EngineManager integration, Lines 488-501: Dynamic engine reference, Lines 525: EngineManager.shutdown())
- `src/raspimidihub/static/pages/settings.js` (Lines 1048-1062: Updated mode change handler, Lines 993-996: Removed restart warning)

### Current Tasks

#### ✅ Phase 2.2: Audio Device Discovery (Complete)
- ✅ Implemented ALSA audio device scanning via `/proc/asound/cards`
- ✅ Added USB topology extraction for stable device IDs
- ✅ Implemented stable device identification using USB serial numbers
- ✅ Added device capability detection (sample rates, channels)
- ✅ Created AudioDevice objects with proper metadata

#### ✅ Phase 2.3: JACK Port Management (Complete)
- ✅ Implemented JACK port discovery via `jack_lsp` command
- ✅ Added audio connection management (`connect_devices`, `disconnect_devices`)
- ✅ Implemented channel mapping support for connections
- ✅ Added connection state tracking with AudioConnection objects
- ✅ Integrated with `jack_connect`/`jack_disconnect` CLI tools

#### ✅ Phase 2.4: Hot-Plug Detection (Complete)
- ✅ Implemented inotify-style monitoring for `/proc/asound/cards`
- ✅ Added device addition/removal event handling
- ✅ Integrated with SSE callback system for UI updates
- ✅ Implemented connection cleanup on device removal
- ✅ Added proper device state tracking

#### 🔄 Phase 2.5: Routing Persistence (In Progress)
- ✅ Extended config.json schema for audio routing (already in DEFAULT_CONFIG)
- ✅ Implemented `_load_audio_routing_config()` method
- ✅ Implemented `_save_audio_routing_config()` method
- ✅ Added `_scan_and_connect()` for MidiEngine compatibility
- ✅ Implemented saved connection restoration on startup
- [x] Full integration with autosave system (audio edits persist via immediate config.asave(); no debounced tier needed)

#### 📋 Phase 2.6: JACK Server Management (Complete)
- ✅ Implemented JACK server startup with appropriate parameters
- ✅ Added JACK daemon detection and automatic startup
- ✅ Implemented proper JACK server shutdown in cleanup
- ✅ Added JACK client initialization structure

**Key AudioEngine Features Implemented:**
- Complete AudioEngine class (~600+ lines of code)
- ALSA device discovery with stable identification
- JACK integration via command-line tools
- Hot-plug detection and handling
- Connection management with channel mapping
- Configuration persistence and restoration
- Compatibility layer with existing MidiEngine interface

#### 📋 Phase 2.3: JACK Port Management (Complete)
- [x] Implement JACK port enumeration (`jack_lsp -p`, parsed with direction/type)
- [x] Add connection management logic (real port names; honest failure on 0 wires)
- [x] Implement connection state tracking

#### 📋 Phase 2.4: Hot-Plug Detection (Complete — poll watchdog, not inotify)
- [ ] ~~Implement inotify monitoring for audio devices~~ superseded: 2 s /proc/asound poll + jackd/bridge liveness in the same loop rebuilds the graph and re-wires saved connections
- [x] Add device state update handling (add/remove cards, stale-device cleanup)
- [x] Integrate with SSE event system (`connection-changed` on create/delete)

#### 📋 Phase 2.5: Routing Persistence (Complete)
- [x] Extend config.json schema for audio routing (`audio_routing.connections` + `.devices`)
- [x] Implement routing restoration on startup (`_scan_and_connect` re-runs positional auto-discovery against live ports)
- [x] Integrate with autosave system (per-edit asave + snapshot path is mode-aware, Save/flush work in audio mode)

### Pending Phases

- Phase 3: Audio Routing UI (1-2 weeks)
- Phase 4: Advanced Audio Features (1-2 weeks)
- Phase 5: Integration & Testing (1 week)

**Major Achievement: Dynamic Mode Switching**
The system now supports seamless switching between MIDI and Audio modes without requiring a system restart. The EngineManager provides:
- Clean engine lifecycle management
- Dynamic engine switching with proper resource cleanup
- Safe fallback and error recovery
- Integration with existing configuration and API systems

**Next Steps:**
Implementing the AudioEngine core with JACK integration for USB audio device discovery and routing.

---

## Executive Summary

This plan details the implementation of USB audio routing capabilities for RaspiMIDIHub, transforming it into a dual-mode routing appliance (MIDI OR Audio, never both simultaneously). The implementation leverages existing architectural patterns and adds audio routing as a parallel mode to the existing MIDI routing functionality.

**Estimated Timeline:** 3-5 weeks for full implementation  
**Complexity:** Medium (builds on proven patterns)  
**Risk Level:** Low (mutually exclusive modes eliminate real-time conflicts)

---

## Architecture Overview

### Design Philosophy

**Core Principle:** "Same patterns, different domain"

The audio routing implementation mirrors the existing MIDI routing architecture:
- Mode selection at startup (MIDI or Audio, never both)
- Parallel engine structure (`AudioEngine` ≈ `MidiEngine`)
- Unified routing matrix UI patterns
- Same configuration persistence system
- Same hot-plug detection patterns

### System Modes

```
┌─────────────────────────────────────────┐
│         RaspiMIDIHub Startup           │
│         (Read config.json)             │
└──────────────┬──────────────────────────┘
               │
        ┌──────┴──────┐
        │   mode?     │
        └──────┬──────┘
         ┌─────┴─────┐
         │           │
    MIDI mode    Audio mode
         │           │
    ┌────┴────┐  ┌───┴────┐
    │ Midi    │  │ Audio  │
    │ Engine  │  │ Engine │
    └─────────┘  └────────┘
```

### Technology Stack

**Audio Routing Layer:** JACK Audio Connection Kit
- `jackd2` server (Raspberry Pi package available)
- Python JACK client bindings (`jack-crt` or `pyjack`)
- Professional-grade, low-latency audio routing
- Sample rate conversion built-in
- Excellent Raspberry Pi support

**Alternative (Future):** PipeWire
- Modern unified audio/video/MIDI subsystem
- Consider for future versions after JACK implementation proves the concept

---

## Implementation Phases

### Phase 0: Prerequisites & Setup (2-3 days)

#### 0.1 Hardware Testing
**Goal:** Verify USB audio interfaces work on Raspberry Pi

**Tasks:**
1. Test your specific USB audio interfaces on Raspberry Pi 4/5
2. Verify ALSA detection:
   ```bash
   cat /proc/asound/cards
   aplay -l
   arecord -l
   ```
3. Test basic JACK functionality:
   ```bash
   sudo apt install jackd2
   jackd -d alsa -d hw:0 -r 48000 -p 128
   ```
4. Verify multi-channel support for your devices
5. Document any device-specific quirks

**Success Criteria:** Both USB audio interfaces detected and functional via JACK

#### 0.2 Development Environment Setup
**Goal:** Prepare development environment for audio work

**Tasks:**
1. Install JACK dependencies:
   ```bash
   sudo apt install jackd2 libjack0
   pip install jack-crt
   # OR
   pip install pyjack
   ```
2. Create development branch:
   ```bash
   git checkout -b feature/audio-routing
   ```
3. Update dependencies documentation

**Files to Create:**
- `AUDIO-ROUTING-IMPLEMENTATION-PLAN.md` (this file)

**Success Criteria:** JACK bindings functional in Python environment

---

### Phase 1: Mode Selection Architecture (3-5 days)

#### 1.1 Configuration Schema Update
**Goal:** Add mode selection to configuration system

**Tasks:**
1. Update `DEFAULT_CONFIG` in `src/raspimidihub/config.py`:
   ```python
   DEFAULT_CONFIG = {
       "mode": "midi",  # "midi" or "audio"
       "mode_locked": False,  # Prevent accidental mode switching
       # ... existing config keys
   }
   ```

2. Update configuration validation logic

3. Add mode migration logic (for existing configs without mode field)

**Files to Modify:**
- `src/raspimidihub/config.py`
- `src/raspimidihub/__init__.py`

#### 1.2 Mode Selection UI
**Goal:** Add mode selector to Settings UI

**Tasks:**
1. Add "Audio/MIDI Mode" section to Settings page
2. Implement radio button or toggle control
3. Add confirmation dialog (requires restart)
4. Add mode indicator in bottom bar (small icon or text)

**UI Design:**
```
Settings → System → Mode
┌────────────────────────────────┐
│  Operating Mode                │
│  ◉ MIDI Routing (default)      │
│  ○ Audio Routing               │
│                                │
│  ⚠️ Changing mode requires     │
│     system restart             │
│                                │
│  [ Apply and Restart ]         │
└────────────────────────────────┘
```

**Files to Modify:**
- `src/raspimidihub/web.py` (Settings HTML)
- `src/raspimidihub/static/js/settings.js` (or equivalent JS)
- `docs/manual/12-settings.md` (documentation)

**Success Criteria:** Mode can be selected, saved, and persists across restarts

#### 1.3 Startup Mode Detection
**Goal:** Launch appropriate engine based on mode

**Tasks:**
1. Update main startup logic in `src/raspimidihub/__init__.py`
2. Implement mode-specific engine initialization:
   ```python
   if config["mode"] == "midi":
       engine = MidiEngine()
   elif config["mode"] "audio":
       engine = AudioEngine()  # To be implemented in Phase 2
   ```

3. Add mode logging and status reporting

**Files to Modify:**
- `src/raspimidihub/__init__.py`
- `src/raspimidihub/midi_engine.py` (ensure clean shutdown)
- `src/raspimidihub/main.py` (if applicable)

**Success Criteria:** System starts in correct mode, logs confirm engine type

---

### Phase 2: Audio Engine Core (1-2 weeks)

#### 2.1 Audio Engine Skeleton
**Goal:** Create AudioEngine class parallel to MidiEngine

**Tasks:**
1. Create `src/raspimidihub/audio_engine.py` (parallel structure to `midi_engine.py`)
2. Implement core AudioEngine class:
   ```python
   class AudioEngine:
       def __init__(self, config):
           self.jack_client = None
           self.devices = {}  # audio_device_id -> AudioDevice
           self.connections = []  # List of active connections
           self.config = config

       async def initialize(self):
           """Initialize JACK client and start processing"""
           pass

       async def shutdown(self):
           """Clean shutdown of JACK client and connections"""
           pass
   ```

3. Implement JACK client management:
   - JACK server startup/shutdown
   - JACK client registration
   - Port registration and management
   - Callback handling

**Files to Create:**
- `src/raspimidihub/audio_engine.py` (~800-1200 lines when complete)

**Dependencies:**
- JACK Python bindings (`jack-crt` or `pyjack`)
- ctypes for JACK C API (if needed)

#### 2.2 Audio Device Discovery
**Goal:** Scan and identify USB audio interfaces

**Tasks:**
1. Implement ALSA audio device scanning:
   ```python
   def _scan_alsa_devices(self):
       """Scan for USB audio devices via ALSA"""
       # Read /proc/asound/cards
       # Query ALSA device capabilities
       # Extract USB topology info
   ```

2. Implement JACK device detection:
   ```python
   def _scan_jack_devices(self):
       """Discover JACK audio ports"""
       # Enumerate JACK ports
       # Group ports by device
       # Identify physical vs virtual ports
   ```

3. Create AudioDevice class (parallel to MidiDevice):
   ```python
   class AudioDevice:
       def __init__(self):
           self.device_id = ""  # Stable identifier
           self.name = ""  # Device name
           self.inputs = []  # List of input ports
           self.outputs = []  # List of output ports
           self.sample_rates = []  # Supported sample rates
           self.channels = {}  # Channel information
           self.usb_topology = ""  # USB bus/port path
   ```

4. Implement stable device identification:
   - Use USB serial numbers when available
   - Fall back to sysfs topology paths
   - Integrate with existing `device_id.py` patterns

**Files to Modify:**
- `src/raspimidihub/audio_engine.py` (device discovery methods)
- `src/raspimidihub/device_id.py` (add audio device ID logic)

**Success Criteria:** USB audio interfaces detected and identified reliably

#### 2.3 JACK Port Management
**Goal:** Manage JACK audio ports and connections

**Tasks:**
1. Implement port enumeration:
   ```python
   def _get_audio_ports(self):
       """Get all JACK audio ports grouped by device"""
       # Returns: {"device_id": {"inputs": [], "outputs": []}}
   ```

2. Implement connection management:
   ```python
   async def connect(self, source_device, dest_device, mapping=None):
       """Create audio connection between devices"""
       # JACK port connection
       # Apply channel mapping if provided
       # Store connection in state

   async def disconnect(self, source_device, dest_device):
       """Remove audio connection"""
       # JACK port disconnection
       # Update state
   ```

3. Implement connection state tracking:
   ```python
   class AudioConnection:
       def __init__(self):
           self.source_device = ""
           self.dest_device = ""
           self.channel_mapping = {}  # "out_ch" -> "in_ch"
           self.enabled = True
           self.gain = {}  # Per-channel gain
   ```

**Files to Modify:**
- `src/raspimidihub/audio_engine.py`

**Success Criteria:** Can create and destroy JACK audio connections programmatically

#### 2.4 Hot-Plug Detection
**Goal:** Detect USB audio interface connect/disconnect events

**Tasks:**
1. Implement `inotify` monitoring for `/proc/asound`:
   ```python
   async def _monitor_hotplug(self):
       """Monitor for audio device hot-plug events"""
       # Similar to existing MIDI hot-plug detection
       # Watch /proc/asound/card* files
   ```

2. Implement device state updates:
   - Add device on connection
   - Remove connections on disconnection
   - Attempt to restore saved connections on reconnect

3. Integrate with existing SSE event system for UI updates

**Files to Modify:**
- `src/raspimidihub/audio_engine.py`
- `src/raspimidihub/web.py` (SSE event types)

**Success Criteria:** Device plug/unplug detected and handled gracefully

#### 2.5 Routing Matrix Persistence
**Goal:** Save and restore audio routing configurations

**Tasks:**
1. Extend `config.json` schema:
   ```json
   {
     "mode": "audio",
     "audio_routing": {
       "connections": [
         {
           "source": "audio-device-1",
           "dest": "audio-device-2",
           "channel_mapping": {"out:1": "in:1", "out:2": "in:2"},
           "enabled": true,
           "gain": {}
         }
       ],
       "devices": {
         "audio-device-1": {"name": "Interface 1", ...}
       }
     }
   }
   ```

2. Implement routing restoration on startup:
   ```python
   async def restore_routing(self):
       """Restore saved audio routing configuration"""
       # Read audio_routing from config
       # Re-establish JACK connections
       # Apply channel mappings and gains
   ```

3. Integrate with existing autosave system:
   - Mark config dirty when routing changes
   - Autosave after routing changes

**Files to Modify:**
- `src/raspimidihub/config.py`
- `src/raspimidihub/audio_engine.py`

**Success Criteria:** Audio routing persists across restarts and device reconnects

---

### Phase 3: Audio Routing UI (1-2 weeks)

#### 3.1 Routing Matrix UI
**Goal:** Create audio routing matrix interface

**Tasks:**
1. Add "Audio Routing" tab (visible only in audio mode)
2. Implement routing matrix UI (parallel to MIDI matrix):
   - Device list (headers + rows)
   - Connection grid (cells = connect buttons)
   - Connection status indicators
   - Multi-channel connection indicators

3. Implement connection controls:
   - Click cell to toggle connection
   - Right-click for connection options
   - Drag for multi-channel connections

**UI Design:**
```
┌─────────────────────────────────────────┐
│  Audio Routing Matrix                  │
├──────────┬─────────────┬───────────────┤
│          │ Scarlett    │  Behringer    │
│          │ 18i8        │  ADA8200      │
├──────────┼─────────────┼───────────────┤
│ Scarlett │     ●       │      ✓        │
│  18i8    │             │  (2 ch)       │
├──────────┼─────────────┼───────────────┤
│ Behringer│     ✓       │      ●        │
│ ADA8200  │  (8 ch)     │               │
└──────────┴─────────────┴───────────────┘
```

**Files to Modify:**
- `src/raspimidihub/web.py` (HTML templates)
- `src/raspimidihub/static/js/routing-matrix.js` (or equivalent)
- `docs/manual/05-routing-matrix.md` (update for audio context)

**Success Criteria:** Can create and remove audio connections via UI

#### 3.2 Connection Details Panel
**Goal:** Add connection configuration panel

**Tasks:**
1. Implement connection detail overlay (similar to MIDI filter panel)
2. Add channel mapping controls:
   - Source channel selector
   - Destination channel selector
   - Stereo link toggles
   - Multi-channel mapping

3. Add gain controls:
   - Per-channel gain sliders
   - Master gain for connection
   - Gain preset selection

4. Add advanced options:
   - Mute/unmute connection
   - Phase invert toggle
   - Sample rate conversion options

**UI Design:**
```
Connection Details: Scarlett 18i8 → Behringer ADA8200
┌─────────────────────────────────────────┐
│ Channel Mapping                          │
│ ┌─────────┬─────────┬─────────┬───────┐ │
│ │ Source  │ → Dest │  Gain   │ Stereo│ │
│ ├─────────┼─────────┼─────────┼───────┤ │
│ │ Out 1   │ → In 1  │  [===]  │ [✓]   │ │
│ │ Out 2   │ → In 2  │  [===]  │ [✓]   │ │
│ │ Out 3   │ → In 3  │  [===]  │ [  ]  │ │
│ │ ...     │ → ...   │  [===]  │ [  ]  │ │
│ └─────────┴─────────┴─────────┴───────┘ │
│                                         │
│ Master Gain:     [========|]  -6.0 dB   │
│ Connection:      ☐ Mute   ☐ Phase Inv  │
│                                         │
│ [ Apply ]  [ Reset ]  [ Cancel ]       │
└─────────────────────────────────────────┘
```

**Files to Modify:**
- `src/raspimidihub/web.py` (HTML templates)
- `src/raspimidihub/static/js/connection-details.js`
- `docs/manual/06-filters-and-mappings.md` (add audio context)

**Success Criteria:** Can configure detailed channel mapping and gain

#### 3.3 Device Information Display
**Goal:** Show audio device capabilities and status

**Tasks:**
1. Implement device info panel (similar to MIDI device details)
2. Display device information:
   - Name and model
   - Supported sample rates
   - Input/output channel count
   - Current sample rate and buffer size
   - USB topology path

3. Show real-time status:
   - Activity indicators (signal present)
   - Level meters (if possible)
   - Connection count

**UI Design:**
```
Device Details: Focusrite Scarlett 18i8
┌─────────────────────────────────────────┐
│ Information                             │
│ Model: Scarlett 18i8 USB               │
│ Sample Rates: 44.1, 48, 96 kHz          │
│ Inputs: 18 analog + 8 ADAT              │
│ Outputs: 18 analog + 8 ADAT             │
│                                         │
│ Status                                  │
│ Current Rate: 48 kHz                    │
│ Buffer Size: 128 samples                │
│ Active Connections: 2                   │
│                                         │
│ Signal Activity                         │
│ [||||||||||     ] Input 1-2             │
│ [|||||          ] Input 3-4             │
│ [|||||||||||||| ] Output 1-2            │
└─────────────────────────────────────────┘
```

**Files to Modify:**
- `src/raspimidihub/web.py`
- `docs/manual/05-routing-matrix.md`

**Success Criteria:** Device capabilities and status clearly displayed

---

### Phase 4: Advanced Audio Features (1-2 weeks)

#### 4.1 Channel Mapping Implementation
**Goal:** Implement flexible audio channel mapping

**Tasks:**
1. Implement channel mapping logic in `AudioEngine`:
   ```python
   def apply_channel_mapping(self, connection, mapping):
       """Apply channel mapping to JACK connection"""
       # Create JACK connections based on mapping
       # Handle stereo linking
       # Apply gain settings
   ```

2. Support common configurations:
   - Stereo (2-channel)
   - Surround (5.1, 7.1)
   - Multi-channel ad-hoc routing
   - Split mono channels

3. Add mapping presets:
   - Stereo pair
   - All channels
   - Custom mappings

**Files to Modify:**
- `src/raspimidihub/audio_engine.py`

#### 4.2 Gain Control Implementation
**Goal:** Implement per-channel gain control

**Tasks:**
1. Implement gain control logic:
   ```python
   def set_connection_gain(self, connection, channel, gain_db):
       """Set gain for specific channel in connection"""
       # Use JACK gain control or add gain plugin
   ```

2. Gain control options:
   - JACK native gain (if available)
   - Gain via JACK gain processor
   - Gain via simple JACK plugin

3. Implement gain presets:
   - Unity (+0 dB)
   - -6 dB, -12 dB, etc.
   - Custom gain values

**Files to Modify:**
- `src/raspimidihub/audio_engine.py`

#### 4.3 Sample Rate Handling
**Goal:** Handle devices with different sample rates

**Tasks:**
1. Implement sample rate detection:
   ```python
   def get_device_sample_rate(self, device):
       """Get current sample rate for device"""
       # Query JACK device rate
   ```

2. Implement sample rate locking:
   - Require common rate across connected devices
   - Show warning if rates differ
   - Suggest optimal rate

3. Integrate JACK sample rate conversion:
   - Automatic SRC if needed
   - SRC quality settings

**Files to Modify:**
- `src/raspimidihub/audio_engine.py`
- `src/raspimidihub/config.py`

---

### Phase 5: Integration & Testing (1 week)

#### 5.1 System Integration
**Goal:** Integrate audio routing with existing system

**Tasks:**
1. Update main application startup flow
2. Ensure clean mode switching
3. Integrate with existing backup system
4. Update error handling and logging

**Files to Modify:**
- `src/raspimidihub/__init__.py`
- `src/raspimidihub/main.py`
- `src/raspimidihub/web.py` (error handling)

#### 5.2 Testing Suite
**Goal:** Comprehensive testing of audio routing

**Tasks:**
1. Manual testing checklist:
   - [ ] Single device routing
   - [ ] Multi-device routing
   - [ ] Hot-plug detection
   - [ ] Configuration persistence
   - [ ] Channel mapping
   - [ ] Gain control
   - [ ] Mode switching
   - [ ] UI responsiveness

2. Performance testing:
   - Latency measurements
   - CPU usage monitoring
   - USB bandwidth testing
   - Multi-channel stress test

3. Compatibility testing:
   - Different USB audio interfaces
   - Multi-channel devices (8+ channels)
   - Different sample rates
   - Long-running stability

#### 5.3 Documentation Updates
**Goal:** Update user and technical documentation

**Tasks:**
1. Update user manual:
   - `docs/manual/README.md` (add audio routing chapter reference)
   - `docs/manual/05-routing-matrix.md` (add audio routing context)
   - `docs/manual/12-settings.md` (document mode selection)
   - Create new chapter: `docs/manual/15-audio-routing.md`

2. Update technical documentation:
   - `docs/manual/17-technical-reference.md` (audio architecture)

3. Update README.md:
   - Add audio routing to feature list
   - Update hardware requirements

**Files to Modify:**
- `docs/manual/README.md`
- `docs/manual/05-routing-matrix.md`
- `docs/manual/12-settings.md`
- `docs/manual/15-audio-routing.md` (new)
- `docs/manual/17-technical-reference.md`
- `README.md`

#### 5.4 Performance Optimization
**Goal:** Optimize audio routing performance

**Tasks:**
1. Profile JACK client performance
2. Optimize JACK callback handling
3. Tune real-time scheduling parameters
4. Optimize UI update frequency

**Files to Modify:**
- `src/raspimidihub/audio_engine.py`
- `scripts/setup-performance.sh` (if applicable)

---

## Dependencies & Requirements

### System Dependencies

```bash
# Core dependencies
sudo apt install jackd2 libjack0

# Optional (for specific use cases)
sudo apt install jackd2-firewire  # FireWire audio support
sudo apt install a2jmidid         # ALSA MIDI to JACK bridge (if needed)
```

### Python Dependencies

```bash
# JACK Python bindings
pip install jack-crt
# OR
pip install pyjack

# Add to requirements.txt or pyproject.toml
```

### Hardware Requirements

- Raspberry Pi 4 or 5 (recommended for audio processing)
- USB audio interfaces (tested and compatible)
- USB 2.0+ ports (sufficient for typical audio routing)
- Power supply sufficient for USB devices

---

## Configuration Schema

### Updated config.json Structure

```json
{
  "mode": "audio",
  "mode_locked": false,
  "audio_routing": {
    "connections": [
      {
        "source": "audio-device-1",
        "dest": "audio-device-2",
        "channel_mapping": {
          "out:1": "in:1",
          "out:2": "in:2"
        },
        "enabled": true,
        "gain": {
          "out:1": 0.0,
          "out:2": 0.0
        },
        "muted": false,
        "phase_invert": false
      }
    ],
    "devices": {
      "audio-device-1": {
        "name": "Focusrite Scarlett 18i8",
        "usb_topology": "1-1.3",
        "serial": "scarlett-18i8-12345",
        "preferred_sample_rate": 48000
      }
    },
    "global_settings": {
      "sample_rate": 48000,
      "buffer_size": 128,
      "gain_processor_type": "jack_native"
    }
  },
  "midi_routing": {
    // (Existing MIDI routing schema - kept but not used in audio mode)
  }
}
```

---

## API Extensions

### New REST Endpoints

```python
# Audio routing endpoints
@server.route("/api/audio/devices", methods=["GET"])
async def get_audio_devices():
    """Get list of audio devices"""

@server.route("/api/audio/connections", methods=["GET", "POST"])
async def audio_connections():
    """Get or create audio connections"""

@server.route("/api/audio/connections/<id>", methods=["DELETE"])
async def delete_audio_connection(id):
    """Delete audio connection"""

@server.route("/api/audio/connections/<id>/config", methods=["PUT"])
async def update_connection_config(id):
    """Update connection channel mapping and gain"""
```

### New SSE Event Types

```python
# Audio routing events
send_sse("audio:device_added", device_data)
send_sse("audio:device_removed", device_id)
send_sse("audio:connection_added", connection_data)
send_sse("audio:connection_removed", connection_id)
send_sse("audio:connection_updated", connection_data)
send_sse("audio:signal_level", level_data)
```

---

## Risk Assessment & Mitigation

### Technical Risks

**Risk 1: JACK Performance Issues**
- **Likelihood:** Medium
- **Impact:** High
- **Mitigation:** Extensive performance testing, tuning of JACK parameters
- **Fallback:** Document alternative audio routing options

**Risk 2: USB Bandwidth Saturation**
- **Likelihood:** Low (for typical use cases)
- **Impact:** Medium
- **Mitigation:** Document device and channel limitations
- **Testing:** Stress test with multi-channel interfaces

**Risk 3: Device Compatibility Issues**
- **Likelihood:** Medium
- **Impact:** Medium
- **Mitigation:** Test with specific USB interfaces, document known issues
- **Fallback:** Provide device compatibility list

### Project Risks

**Risk 4: Implementation Complexity Underestimated**
- **Likelihood:** Medium
- **Impact:** Medium
- **Mitigation:** Phased implementation, regular testing
- **Contingency:** Extend timeline by 1-2 weeks

**Risk 5: UI/UX Complexity**
- **Likelihood:** Low
- **Impact:** Low
- **Mitigation:** Reuse existing UI patterns
- **Simplification:** Start with basic routing, add features later

---

## Success Criteria

### Phase Completion Criteria

**Phase 0 (Prerequisites):**
- ✅ JACK installed and functional
- ✅ Test audio devices working on Pi
- ✅ Development branch created

**Phase 1 (Mode Selection):**
- ✅ Mode selector in Settings UI
- ✅ Mode persists across restarts
- ✅ System starts in correct mode
- ✅ Existing MIDI mode unchanged

**Phase 2 (Audio Engine):**
- ✅ USB audio devices detected and identified
- ✅ JACK connections can be created/destroyed
- ✅ Hot-plug detection working
- ✅ Routing persistence functional

**Phase 3 (Audio UI):**
- ✅ Routing matrix UI functional
- ✅ Connection details panel working
- ✅ Device information display complete
- ✅ Real-time status updates working

**Phase 4 (Advanced Features):**
- ✅ Channel mapping implemented
- ✅ Gain control functional
- ✅ Sample rate handling complete

**Phase 5 (Integration):**
- ✅ All integration tasks complete
- ✅ Testing checklist passed
- ✅ Documentation updated
- ✅ Performance optimized

### Final Acceptance Criteria

1. **Functional:** USB audio routing works end-to-end
2. **Stable:** No crashes or glitches during normal operation
3. **Performant:** Audio latency <10ms, CPU usage <50%
4. **Usable:** Intuitive UI, clear documentation
5. **Maintainable:** Clean code, follows existing patterns
6. **Tested:** Comprehensive testing completed

---

## Future Enhancements (Post-Implementation)

### Potential Features for Future Versions

1. **PipeWire Integration:** Migrate from JACK to PipeWire
2. **Audio Plugins:** Implement audio plugins (EQ, compression, effects)
3. **Matrix Mixing:** Full matrix mixing capabilities
4. **Bluetooth Audio:** Route Bluetooth audio to/from USB interfaces
5. **Network Audio:** RTP audio streaming (similar to existing RTP-MIDI)
6. **Recording/Playback:** Basic recording and playback capabilities
7. **Metering:** More detailed level metering and analysis
8. **Profiles:** Audio routing profiles for different setups

---

## Notes for Implementation

### Code Patterns to Follow

1. **Async/Await:** Use existing async patterns throughout
2. **Error Handling:** Follow existing error handling patterns
3. **Logging:** Use existing logging infrastructure
4. **SSE Events:** Integrate with existing SSE event system
5. **Configuration:** Extend existing configuration system
6. **Device IDs:** Use existing stable device identification patterns

### Architecture Principles

1. **Separation of Concerns:** Audio engine separate from MIDI engine
2. **Mode Isolation:** No cross-mode dependencies at runtime
3. **Shared Infrastructure:** UI, config, persistence shared across modes
4. **Performance First:** Optimize for low latency and stability
5. **User Experience:** Maintain plug-and-play simplicity

### Testing Strategy

1. **Unit Tests:** Test individual components in isolation
2. **Integration Tests:** Test audio engine with JACK
3. **Manual Tests:** Comprehensive manual testing checklist
4. **Performance Tests:** Latency, CPU usage, USB bandwidth
5. **Compatibility Tests:** Various USB audio interfaces

---

## Implementation Timeline

### 3-5 Week Implementation Schedule

```
Week 1: Phase 0 + Phase 1
├── Days 1-3: Prerequisites & Setup
├── Days 4-5: Mode Selection Architecture
└── Days 6-7: Mode Selection UI & Startup

Week 2: Phase 2 (Audio Engine Core)
├── Days 8-10: Audio Engine Skeleton & Device Discovery
├── Days 11-12: JACK Port Management
└── Days 13-14: Hot-Plug Detection & Persistence

Week 3: Phase 3 (Audio Routing UI)
├── Days 15-17: Routing Matrix UI
├── Days 18-19: Connection Details Panel
└── Days 20-21: Device Information Display

Week 4: Phase 4 (Advanced Features)
├── Days 22-24: Channel Mapping Implementation
├── Days 25-26: Gain Control Implementation
└── Days 27-28: Sample Rate Handling

Week 5: Phase 5 (Integration & Testing)
├── Days 29-30: System Integration
├── Days 31-33: Testing Suite
├── Days 34-35: Documentation Updates
└── Days 36-37: Performance Optimization & Final Testing
```

**Buffer:** 1-2 weeks for unexpected issues or additional features

---

## Conclusion

This implementation plan provides a structured path to add USB audio routing to RaspiMIDIHub while maintaining the architectural principles and code quality of the existing system. The phased approach allows for incremental development and testing, with clear success criteria for each phase.

The key design decision of mutually exclusive modes (MIDI OR Audio) dramatically simplifies the implementation and eliminates the most significant technical risks. The existing architecture, patterns, and infrastructure provide a strong foundation for building the audio routing capabilities.

**Next Steps:**
1. Review and refine this plan
2. Set up test environment with Raspberry Pi and USB audio interfaces
3. Begin Phase 0 (Prerequisites & Setup)
4. Proceed with phased implementation

---

**Document Version:** 1.0  
**Last Updated:** 2026-08-25  
**Status:** Ready for Implementation  
