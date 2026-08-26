"""Audio routing engine for USB audio interfaces via JACK.

This module provides audio routing capabilities similar to how MidiEngine
handles MIDI routing, but for USB audio interfaces using the JACK Audio
Connection Kit.
"""

import asyncio
import logging
import os
import re
import tempfile
import time
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class AudioDevice:
    """Represents a USB audio interface or JACK audio device.

    Parallel structure to MidiDevice, providing stable identification
    and capability information for audio interfaces.
    """
    device_id: str = ""  # Stable identifier across reconnects
    name: str = ""  # Device name (e.g., "Focusrite Scarlett 18i8")
    inputs: List[str] = None  # List of input port names
    outputs: List[str] = None  # List of output port names
    sample_rates: List[int] = None  # Supported sample rates
    channels: Dict = None  # Channel information {channel_name: properties}
    usb_topology: str = ""  # USB bus/port path for stable ID
    serial: str = ""  # USB serial number if available
    jack_client_name: str = ""  # Primary JACK client name ("")
    jack_client_names: List[str] = None  # ALL JACK clients carrying this card ('system', or one per bridge direction)
    has_capture: bool = False  # Device has capture (input) capability
    has_playback: bool = True  # Device has playback (output) capability

    def __post_init__(self):
        if self.inputs is None:
            self.inputs = []
        if self.outputs is None:
            self.outputs = []
        if self.sample_rates is None:
            self.sample_rates = [44100, 48000]  # Common rates
        if self.channels is None:
            self.channels = {}
        if self.jack_client_names is None:
            self.jack_client_names = []


@dataclass
class AudioConnection:
    """Represents an audio routing connection between devices.

    Parallel structure to MIDI connections, supporting flexible
    channel mapping and gain control.
    """
    source_device: str = ""  # Source device ID
    dest_device: str = ""  # Destination device ID
    channel_mapping: Dict = None  # {"out:1": "in:1", "out:2": "in:2"}
    enabled: bool = True
    gain: Dict = None  # Per-channel gain in dB
    muted: bool = False
    phase_invert: bool = False

    def __post_init__(self):
        if self.channel_mapping is None:
            self.channel_mapping = {}
        if self.gain is None:
            self.gain = {}


class AudioEngine:
    """Audio routing engine using JACK for USB audio interfaces.

    Provides audio routing capabilities parallel to MidiEngine, supporting:
    - USB audio device discovery and identification
    - JACK port management and routing
    - Hot-plug detection for audio interfaces
    - Configuration persistence and restoration
    - Real-time audio routing without restarting
    """

    def __init__(self):
        self._jack_client = None
        self._devices: Dict[str, AudioDevice] = {}  # device_id -> AudioDevice
        self._connections: List[AudioConnection] = []
        self._config = None
        self._running = False
        self._event_loop_task = None

        # JACK client name
        self._client_name = "RaspiMIDIHub"

        # Change sequence for autosaver (parallel to MidiEngine._change_seq)
        self._change_seq = 0

        # Config dirty tracking (parallel to MidiEngine.config_dirty)
        self._dirty = False

        # Audio routing settings
        self._sample_rate = 48000
        self._buffer_size = 128
        self._jack_ports: List[dict] = []  # Discovered JACK ports

        # Callbacks
        self._on_change_callbacks: List[Callable] = []
        self._on_device_connected_callbacks: List[Callable] = []
        self._on_device_disconnected_callbacks: List[Callable] = []

        # Plugin compatibility (same interface as MidiEngine)
        self._plugin_host = None
        self._ble_bridge = None
        self._network_midi = None
        self._dirty = False
        self._autosaver = None

        # Audio activity tracking
        self._on_midi_event_callbacks: List[Callable] = []
        self._on_transport_start_callbacks: List[Callable] = []

        # Monitor port (like MIDI engine has)
        self._monitor_port = None

        # Hot-plug monitoring
        self._hotplug_task = None
        self._last_device_state: Dict[str, bool] = {}

        # Process ownership of the audio graph. jackd binds exactly ONE
        # ALSA card (the playback-capable USB one, as "system:*"); every
        # OTHER capture/playback-capable USB card is bridged into the
        # graph with alsa_in / alsa_out under its own stable client name.
        # We track the Popen handles we spawned so cleanup kills only
        # what we own — and the hotplug watchdog can respawn on death.
        self._jack_proc: Optional["object"] = None      # our jackd Popen (None if pre-existing)
        self._bridge_procs: Dict[str, object] = {}       # jack client name -> Popen
        self._jack_errfile = None                        # jackd stderr (read on death for diagnosis)
        self._bridge_errfiles: Dict[str, object] = {}    # bridge client name -> stderr file
        self._next_graph_retry = 0.0                     # monotonic time of next bring-up retry
        self._jack_clients_by_card: Dict[int, List[str]] = {}  # card_num -> its JACK client names
        self._card_of_device: Dict[str, int] = {}        # device_id -> ALSA card num
        self._jack_was_external = False                  # True if jackd was already running at start
        self._owner_card: Optional[int] = None           # card our own jackd binds (None otherwise)

    @property
    def devices(self) -> List[AudioDevice]:
        """List of discovered audio devices."""
        return list(self._devices.values())

    @property
    def connections(self) -> List[AudioConnection]:
        """List of active audio connections."""
        return self._connections

    @property
    def config_dirty(self) -> bool:
        """Whether the configuration has unsaved changes."""
        return self._dirty

    def start(self):
        """Start the audio engine and JACK client.

        Initializes JACK client and begins device discovery.
        This is the synchronous start method called during initialization.
        """
        if self._running:
            log.warning("AudioEngine already running")
            return

        log.info("Starting AudioEngine")
        try:
            self._initialize_jack()
            self._discover_audio_devices()

            # Start hot-plug monitoring
            self._start_hotplug_monitoring()

            self._running = True
            log.info("AudioEngine started successfully")
        except Exception as e:
            log.error("Failed to start AudioEngine: %s", e)
            self._cleanup()
            raise

    def stop(self):
        """Stop the audio engine and JACK client.

        Clean shutdown of JACK client and all audio routing.
        """
        if not self._running:
            return

        log.info("Stopping AudioEngine")
        self._running = False

        # Stop hot-plug monitoring
        if self._hotplug_task:
            self._hotplug_task.cancel()
            self._hotplug_task = None

        self._cleanup()

    async def astop(self):
        """Async stop method for compatibility."""
        self.stop()

    async def run_event_loop(self):
        """Run the audio engine event loop.

        For compatibility with MidiEngine interface. The audio engine
        primarily uses JACK callbacks rather than a polling loop like MIDI.
        """
        log.info("AudioEngine event loop running")

        try:
            # Audio engine uses JACK callbacks, so we just keep the loop alive
            # and handle async events
            while self._running:
                await asyncio.sleep(1)

                # Periodic tasks could go here
                # - Check for device changes
                # - Update monitoring
                # - Handle configuration autosave

        except asyncio.CancelledError:
            log.info("AudioEngine event loop cancelled")
            raise
        finally:
            log.info("AudioEngine event loop ended")

    def _initialize_jack(self):
        """Bring up the JACK graph for ALL USB audio cards.

        One jackd instance owns exactly one ALSA card — the first
        playback-capable one we can find (it appears in the graph as the
        "system" client). Every OTHER capture/playback-capable USB card is
        bridged into the graph by a small alsa_in / alsa_out helper process
        under a stable client name. Without the bridges only ONE of the two
        USB gadgets would exist inside JACK and cross-device routing could
        never physically connect.

        Safe to call repeatedly: a server we didn't start is left alone,
        and re-running against a live graph only fills gaps (no daemon
        restart, no duplicate bridges).
        """
        import subprocess

        log.info("Initializing JACK graph: %s", self._client_name)
        try:
            try:
                result = subprocess.run(["jack_lsp"], capture_output=True, timeout=2)
                jack_running = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                jack_running = False

            if jack_running and self._owner_card is None:
                # A server answers that WE did not start. Keep hands off
                # entirely — fighting someone else's rig is worse than no
                # routing. Mark it external so the retry loop stays quiet.
                self._jack_was_external = True
                log.info("Pre-existing JACK server detected — hub does not "
                         "manage this audio graph")
                return

            alsa_devices = self._scan_alsa_devices()

            owner_card = self._owner_card
            if not jack_running:
                self._jack_was_external = False
                owner_card = self._pick_owner_card(alsa_devices)
                if owner_card is None:
                    log.warning("No ALSA cards at all — no audio graph possible")
                    return
                if not self._start_jack_server(owner_card):
                    # Refused (rc + stderr tail already logged); the 30 s
                    # retry loop brings bring-up back around.
                    return
            elif owner_card is None:
                owner_card = self._pick_owner_card(alsa_devices)

            # Bridge every other USB card into the graph — but only when a
            # server is actually answering. Spawning bridges with no JACK
            # daemon used to produce alsa_in processes that die within
            # seconds and retrigger endless watchdog rebuilds.
            if self._server_reachable():
                self._bridge_secondary_cards(alsa_devices, owner_card)
                if owner_card is not None:
                    self._jack_clients_by_card[owner_card] = ["system"]
            else:
                if self._jack_proc is not None and self._jack_proc.poll() is None:
                    log.warning("jackd running but not answering yet — "
                                "bridging deferred; watchdog will reconcile")
                else:
                    log.error("No usable JACK server (jackd failed to bind or "
                              "died) — devices still listed, connects will "
                              "fail until bring-up succeeds (retrying every "
                              "30 s).")
                # Devices are discovered independently of the graph, so the
                # UI keeps showing them; the hot-plug monitor retries this
                # bring-up periodically.

        except Exception as e:
            log.error("Failed to initialize JACK graph: %s", e)
            raise

    def _is_usb_card(self, card_num: int) -> bool:
        """True when the ALSA card hangs off the USB bus."""
        try:
            link = Path(f"/sys/class/sound/card{card_num}/device")
            if link.is_symlink():
                return "usb" in str(link.resolve()).lower()
        except Exception:
            pass
        return False

    def _pick_owner_card(self, devices: List[dict]) -> Optional[int]:
        """Choose which ALSA card jackd itself binds to.

        Priority: USB + playback-capable first (it hosts system:playback_*,
        what a destination gadget needs), then any playback-capable card,
        then the first card of any kind.
        """
        usb_play = [d for d in devices
                    if d.get("has_playback") and self._is_usb_card(d["card"])]
        if usb_play:
            return usb_play[0]["card"]
        play = [d for d in devices if d.get("has_playback")]
        if play:
            return play[0]["card"]
        return devices[0]["card"] if devices else None

    @staticmethod
    def _jack_safe_name(name: str) -> str:
        """Sanitize an ALSA name into a valid JACK client name."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip())
        return safe[:24] or f"audio"

    @staticmethod
    def _read_err_tail(errfile) -> str:
        """Last ~400 bytes of a subprocess's captured stderr for logs."""
        if errfile is None:
            return ""
        try:
            errfile.seek(0, 2)          # end
            size = errfile.tell()
            errfile.seek(max(0, size - 400))
            data = errfile.read()
            errfile.seek(0, 2)
            text = data.decode("utf-8", "replace").strip()
            return f": {text}" if text else ""
        except Exception:
            return ""

    def _server_reachable(self, timeout: float = 1.5) -> bool:
        """True when a JACK server answers `jack_lsp` in OUR runtime dir."""
        import subprocess
        try:
            probe = subprocess.run(["jack_lsp"], capture_output=True, timeout=timeout)
            return probe.returncode == 0
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False

    def _start_jack_server(self, owner_card: int) -> bool:
        """Start jackd bound to `owner_card`. Stores our Popen so cleanup
        kills only what we spawned — an externally-started jackd is left
        alone entirely (_jack_was_external). Returns True when the server
        exists afterwards (answered jack_lsp, or at least stays alive)."""
        import subprocess

        target_device = f"hw:{owner_card}"
        cmd = [
            "jackd",
            "-d", "alsa",
            "-d", target_device,
            "-r", "48000",       # (alsa driver) sample rate
            "-p", "256",
            "-n", "3",
        ]
        # No --name: everything after `-d alsa` is parsed by the ALSA
        # *driver*, which rejects unknown long options and exits 255 after
        # printing its usage — confirmed by the captured stderr on real
        # hardware. A server-level `-n <name>` would have to precede -d;
        # the default server name is fine for us.
        # No scheduling flag on purpose: jackd2 defaults to RT mode (-r is
        # actually NO-realtime there). The appliance runs as root, so RT
        # grants succeed.
        # Also deliberately NOT -T: on jackd2 that marks a TEMPORARY
        # server which exits once its last client disconnects — a bridge
        # restart must never be able to kill the daemon.
        log.info("Starting jackd: %s", " ".join(cmd))
        errf = tempfile.TemporaryFile()
        self._jack_errfile = errf
        # Without a D-Bus session bus (our systemd service is headless) the
        # default device-reservation handshake fails with "cannot be
        # acquired" and jackd refuses the card outright. This env switch
        # makes it take the device directly — right for an appliance that
        # owns its sound cards.
        spawn_env = dict(os.environ)
        spawn_env["JACK_NO_AUDIO_RESERVATION"] = "1"
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=errf,
                env=spawn_env,
                start_new_session=True,
            )
        except FileNotFoundError:
            log.warning("jackd binary not found — audio routing unavailable")
            errf.close()
            self._jack_errfile = None
            return False

        # jackd takes a moment to open the device before clients can attach.
        for _ in range(20):                      # up to ~4 s
            time.sleep(0.2)
            if process.poll() is not None:
                break
            try:
                probe = subprocess.run(["jack_lsp"], capture_output=True, timeout=1)
                if probe.returncode == 0:
                    self._jack_proc = process
                    self._owner_card = owner_card
                    log.info("jackd started (PID %d) on %s", process.pid, target_device)
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        if process.poll() is not None:
            # Typical cause of rc=255: another process already holds the ALSA
            # device (EBUSY). The captured stderr tail says it in jackd's own
            # words — surface it instead of swallowing it.
            log.error("jackd exited immediately (rc=%s) on %s "
                      "(another process may own hw:%s)%s",
                      process.returncode, target_device, owner_card,
                      self._read_err_tail(errf))
            errf.close()
            self._jack_errfile = None
            return False

        # Still alive but never answered jack_lsp — leave it running,
        # it may just be slow; watchdog will reconcile later.
        self._jack_proc = process
        self._owner_card = owner_card
        log.warning("jackd alive but did not answer jack_lsp within 4 s")
        return True

    def _apply_jack_client_names(self):
        """Stamp the resolved JACK client names onto the live AudioDevice
        objects using the device_id -> card map recorded at discovery.
        Devices without a matching card get no names — unroutable."""
        for device_id, dev in self._devices.items():
            card = self._card_of_device.get(device_id)
            names = list(self._jack_clients_by_card.get(card, []))
            dev.jack_client_names = names
            dev.jack_client_name = names[0] if names else ""

    def _bridge_secondary_cards(self, devices: List[dict], owner_card: int):
        """Spawn alsa_in / alsa_out bridges so every OTHER USB card shows
        up as its own JACK client.

        Idempotent: any target client name already visible in the graph
        is left alone and merely recorded — so this is safe to re-call on
        hot-plug or after a partial bring-up without ever double-spawning.
        Requires jack-example-tools (Debian); absence is logged once and
        bridged routing is then impossible."""

        missing = []
        import shutil
        import subprocess

        # One snapshot of the live graph's client names for the whole pass.
        live_clients = set()
        try:
            lsp = subprocess.run(["jack_lsp"], capture_output=True, timeout=2)
            if lsp.returncode == 0:
                live_clients = {
                    line.split(":", 1)[0]
                    for line in lsp.stdout.decode("utf-8", "replace").splitlines()
                    if ":" in line
                }
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass

        for dev in devices:
            card = dev["card"]
            if card == owner_card or not self._is_usb_card(card):
                continue
            base = self._jack_safe_name(dev.get("name", ""))

            # A card is neither inherently source nor destination — bridge
            # EVERY direction it offers so the routing matrix can pick.
            #   alsa_out : JACK -> card playback  (destination side)
            #   alsa_in  : card capture -> JACK   (source side)
            want = []
            if dev.get("has_playback"):
                # Carries the plain client name; destination gadgets are the
                # common case and unsuffixed reads best in port listings.
                want.append(("alsa_out", "playback", base))
            if dev.get("has_capture"):
                want.append(("alsa_in", "capture", f"{base}-in"))
            if not want:
                continue

            already = [c for _, _, c in want if c in live_clients]
            todo = [(t, r, c) for t, r, c in want if c not in live_clients]
            if already:
                merged = dict.fromkeys(self._jack_clients_by_card.get(card, [])
                                       + already)
                self._jack_clients_by_card[card] = list(merged)

            def spawn_bridge(tool: str, role: str, cname: str) -> bool:
                args = [tool, "-j", cname, "-d", f"hw:{card}",
                        "-r", "48000", "-c", "2", "-n", "2", "-q", "1"]
                path = shutil.which(tool)
                if path is None:
                    if tool not in missing:
                        missing.append(tool)
                    return False
                errf = tempfile.TemporaryFile()
                try:
                    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                            stderr=errf,
                                            start_new_session=True)
                except OSError as e:
                    log.warning("Failed to spawn %s for card %d: %s",
                                tool, card, e)
                    errf.close()
                    return False

                # A spawned process is not a working bridge. `alsa_in` starts
                # fine with no JACK server anywhere and dies seconds later;
                # only success counts once the client actually registers.
                registered = False
                for _ in range(6):                # up to ~3 s
                    time.sleep(0.5)
                    if proc.poll() is not None:
                        break
                    try:
                        lsp = subprocess.run(["jack_lsp"], capture_output=True,
                                             timeout=1)
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        continue
                    if lsp.returncode == 0 and any(
                            line.split(":", 1)[0] == cname
                            for line in (lsp.stdout or b"").decode(
                                "utf-8", "replace").splitlines()):
                        registered = True
                        break

                if not registered:
                    rc_note = (f"exited rc={proc.returncode}"
                               if proc.poll() is not None else "never registered")
                    log.warning("%s for card %d failed (%s)%s",
                                tool, card, rc_note, self._read_err_tail(errf))
                    if proc.poll() is None:       # alive but useless — stop it
                        proc.terminate()
                    errf.close()
                    return False

                self._bridge_procs[cname] = proc
                self._bridge_errfiles[cname] = errf
                log.info("Bridged card %d (%s) via %s as client '%s'",
                         card, dev.get("name"), role, cname)
                return True

            created = [cname for tool, role, cname in todo
                       if spawn_bridge(tool, role, cname)]
            if created:
                merged = dict.fromkeys(self._jack_clients_by_card.get(card, [])
                                       + created)
                self._jack_clients_by_card[card] = list(merged)

        if missing:
            log.warning("%s not found — install jack-example-tools to route "
                        "through cards other than the jackd host", missing[0])

    def _discover_audio_devices(self):
        """Discover audio devices via ALSA and JACK.

        Scans for USB audio interfaces and creates AudioDevice
        objects with stable identification.
        """
        log.info("Discovering audio devices via ALSA and JACK")

        try:
            # Discover ALSA audio devices
            alsa_devices = self._scan_alsa_devices()
            log.info("Found %d ALSA audio devices", len(alsa_devices))

            # Create AudioDevice objects from discovered hardware
            seen_ids = set()
            for alsa_device in alsa_devices:
                device = self._create_audio_device_from_alsa(alsa_device)
                if device:
                    self._devices[device.device_id] = device
                    seen_ids.add(device.device_id)
                    # Remember which ALSA card backs this device so
                    # _apply_jack_client_names can stamp the right JACK client.
                    self._card_of_device[device.device_id] = alsa_device["card"]
                    log.info("Registered audio device: %s (%s)",
                             device.name, device.device_id)

            # Drop stale bookkeeping for vanished ids (hotplug rescan)
            for gone in set(self._card_of_device) - seen_ids:
                del self._card_of_device[gone]

            # Stamp resolved JACK client names onto each device BEFORE the
            # port scan — port->device association matches by client name.
            self._apply_jack_client_names()

            # Discover JACK ports last: needs named devices to associate.
            self._jack_ports = self._scan_jack_ports()
            log.info("Found %d JACK ports", len(self._jack_ports))

            # Notify callbacks
            self._notify_device_connected()

        except Exception as e:
            log.error("Audio device discovery failed: %s", e)

    def _scan_alsa_devices(self):
        """Scan for ALSA audio devices from /proc/asound."""
        devices = []
        try:
            cards_path = Path("/proc/asound/cards")
            if not cards_path.exists():
                log.warning("ALSA cards file not found")
                return devices

            card_lines = cards_path.read_text().splitlines()
            for line in card_lines:
                # Only bracketed header lines are card records:
                #   " 3 [M8             ]: USB-Audio - M8"
                # The continuation line below each header ("Dirtywave M8 at
                # usb-0000:01:00.0-1.1, high speed") carries colons in its
                # USB path and must NOT be parsed -- attempting it used to
                # raise on int() and abort the whole scan, silently dropping
                # every card that came after (e.g. a two-gadget rig).
                m = re.match(r"\s*(\d+)\s+\[([^\]]*)\]\s*:", line)
                if not m:
                    continue

                card_num = int(m.group(1))
                name = m.group(2).strip()

                # Built-in Pi audio (bcm2835 / vc4-hdmi) never joins the
                # audio graph; USB gadgets only.
                if not self._is_usb_card(card_num):
                    continue

                # Check if device has capture (input) capability
                has_capture = self._check_device_has_capture(card_num)
                has_playback = self._check_device_has_playback(card_num)

                # Get more detailed device info
                device_info = {
                    "card": card_num,
                    "name": name,
                    "id": f"card{card_num}",
                    "has_capture": has_capture,
                    "has_playback": has_playback
                }

                # Extract USB topology if available
                usb_info = self._extract_usb_device_info(card_num)
                if usb_info:
                    device_info.update(usb_info)

                devices.append(device_info)

        except Exception as e:
            log.warning("Failed to scan ALSA devices: %s", e)

        return devices

    def _check_device_has_capture(self, card_num: int) -> bool:
        """Check if device has capture (input) capability."""
        try:
            # Check /proc/asound/card{card_num}/codec#0 for capture info
            # Or use a simpler method by checking device files
            card_path = Path(f"/sys/class/sound/card{card_num}")
            if card_path.exists():
                # Look for capture devices (pcm*c)
                capture_devices = list(card_path.glob("pcm*c"))
                return len(capture_devices) > 0
        except Exception:
            pass
        return False

    def _check_device_has_playback(self, card_num: int) -> bool:
        """Check if device has playback (output) capability."""
        try:
            card_path = Path(f"/sys/class/sound/card{card_num}")
            if card_path.exists():
                # Look for playback devices (pcm*p)
                playback_devices = list(card_path.glob("pcm*p"))
                return len(playback_devices) > 0
        except Exception:
            pass
        return False

    def _extract_usb_device_info(self, card_num: int) -> Optional[dict]:
        """Extract USB device information for stable identification."""
        try:
            card_path = Path(f"/sys/class/sound/card{card_num}")
            if not card_path.exists():
                return None

            device_link = card_path / "device"
            if not device_link.is_symlink():
                return None

            target = device_link.resolve()

            # Extract USB information
            usb_info = {}

            # Get USB bus and device numbers
            path_parts = target.parts
            for i, part in enumerate(path_parts):
                if part.startswith("usb") and "-" in part:
                    # Format: usb1-1.3 -> bus 1, port 1.3
                    usb_info["usb_path"] = "/".join(path_parts[i:i+3])
                    usb_info["usb_bus"] = part.split("-")[0][3:]
                    usb_info["usb_port"] = part.split("-")[1]

                    # Try to get serial from parent directory
                    if i > 0:
                        parent_link = Path("/sys").joinpath(*path_parts[:i])
                        serial_file = parent_link / "serial"
                        if serial_file.exists():
                            usb_info["serial"] = serial_file.read_text().strip()

                    break

            return usb_info if usb_info else None

        except Exception as e:
            log.warning("Failed to extract USB device info for card %d: %s", card_num, e)
            return None

    def _scan_jack_ports(self) -> List[dict]:
        """Scan for JACK audio ports and associate them with devices."""
        ports = []
        try:
            # Check if JACK is running
            import subprocess
            result = subprocess.run(["jack_lsp", "-p"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                current_device = None
                current_port = None
                port_properties = {}

                for line in result.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue

                    # Parse JACK port output
                    if line.startswith("port:") or (":" in line and not line.startswith("properties:")):
                        # Save previous port if exists
                        if current_port:
                            port_info = {"name": current_port, "device": current_device}
                            port_info.update(port_properties)
                            ports.append(port_info)

                        # Parse new port
                        parts = line.split(":")
                        if len(parts) >= 2:
                            device_name = parts[0]
                            port_name = parts[1].strip()

                            # Try to match with known devices
                            current_device = self._find_device_by_jack_name(device_name)
                            current_port = f"{device_name}:{port_name}"
                            port_properties = {}

                    elif line.startswith("properties:"):
                        # Parse port properties
                        props = line.replace("properties:", "").strip()
                        if "input" in props.lower():
                            port_properties["direction"] = "input"
                        elif "output" in props.lower():
                            port_properties["direction"] = "output"
                        if "audio" in props.lower():
                            port_properties["type"] = "audio"
                        elif "midi" in props.lower():
                            port_properties["type"] = "midi"

                # Add last port
                if current_port:
                    port_info = {"name": current_port, "device": current_device}
                    port_info.update(port_properties)
                    ports.append(port_info)

                log.info("Found %d JACK ports", len(ports))
            else:
                log.info("JACK daemon not running or no ports available")

        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning("Failed to scan JACK ports: %s", e)

        return ports

    def _find_device_by_jack_name(self, jack_name: str) -> Optional[str]:
        """Find device ID by any of its JACK client names."""
        for device_id, device in self._devices.items():
            if jack_name in device.jack_client_names:
                return device_id
        return None

    async def connect_devices(self, source_device: str, dest_device: str,
                             channel_mapping: Dict = None) -> bool:
        """Create audio connection between devices via JACK.

        Args:
            source_device: Source device ID
            dest_device: Destination device ID
            channel_mapping: Optional explicit mapping of FULL JACK port
                names {"system:playback_1": "<src>:capture_1", ...}.
                When omitted, ports are auto-discovered by position.

        Returns:
            True only when at least one JACK wire was actually connected —
            a silent graph is never reported as success.
        """
        import subprocess

        if source_device not in self._devices or dest_device not in self._devices:
            log.error("Unknown device in connection request (%s -> %s)",
                      source_device, dest_device)
            return False

        source = self._devices[source_device]
        dest = self._devices[dest_device]

        try:
            # Resolve which real JACK ports carry this edge.
            if channel_mapping:
                port_map = dict(channel_mapping)
            elif not source.jack_client_names or not dest.jack_client_names:
                log.warning("Cannot route %s -> %s: no JACK client bound "
                            "(missing bridge? card unowned?)",
                            source.name, dest.name)
                return False
            else:
                port_map = self._auto_discover_port_mapping(source, dest)

            if not port_map:
                log.warning("No routable JACK ports found for %s -> %s "
                            "(source outputs=%d dest inputs=%d; seen %d jack ports)",
                            source.name, dest.name, len(source.outputs),
                            len(dest.inputs), len(self._jack_ports))
                return False

            connected_pairs = {}
            for src_port, dst_port in port_map.items():
                try:
                    result = subprocess.run(
                        ["jack_connect", src_port, dst_port],
                        capture_output=True, text=True, timeout=5
                    )
                except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                    log.warning("jack_connect failed for %s -> %s: %s",
                                src_port, dst_port, e)
                    continue
                if result.returncode == 0:
                    connected_pairs[src_port] = dst_port
                    log.info("JACK wired: %s -> %s", src_port, dst_port)
                else:
                    stderr = (result.stderr or "").strip()
                    log.warning("jack_connect refused %s -> %s: %s",
                                src_port, dst_port, stderr)

            if not connected_pairs:
                log.error("Audio connection failed: 0/%d wires connected "
                          "for %s -> %s", len(port_map), source.name, dest.name)
                return False

            connection = AudioConnection(
                source_device=source_device,
                dest_device=dest_device,
                channel_mapping=connected_pairs,
                enabled=True
            )
            self._connections.append(connection)
            self.mark_dirty()

            log.info("Audio connection created: %s -> %s (%d channel%s)",
                     source.name, dest.name, len(connected_pairs),
                     "s" if len(connected_pairs) != 1 else "")

            self._fire_on_change()

            return True

        except Exception as e:
            log.error("Failed to create audio connection: %s", e)
            return False

    def _fire_on_change(self):
        """Fan out a routing change to on_change callbacks."""
        for callback in self._on_change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback())
                else:
                    callback()
            except Exception as e:
                log.warning("Connection change callback failed: %s", e)

    async def disconnect_devices(self, source_device: str, dest_device: str) -> bool:
        """Remove audio connection between devices.

        Args:
            source_device: Source device ID
            dest_device: Destination device ID

        Returns:
            True if disconnection successful, False otherwise
        """
        try:
            # Find and remove connection
            connection = None
            for conn in self._connections:
                if conn.source_device == source_device and conn.dest_device == dest_device:
                    connection = conn
                    break

            if connection:
                import subprocess
                source = self._devices.get(source_device)
                dest = self._devices.get(dest_device)

                # Stored channel_mapping holds FULL jack port names
                # ({src_full: dst_full}). Legacy entries written by the old
                # name-synthesis code ("out_1") can't be trusted; rediscover.
                port_map = None
                if connection.channel_mapping and all(
                        ":" in k and ":" in v
                        for k, v in connection.channel_mapping.items()):
                    port_map = connection.channel_mapping
                elif source and dest and source.jack_client_names and dest.jack_client_names:
                    port_map = self._auto_discover_port_mapping(source, dest)

                if port_map:
                    for src_port, dst_port in port_map.items():
                        try:
                            result = subprocess.run(
                                ["jack_disconnect", src_port, dst_port],
                                capture_output=True, text=True, timeout=5
                            )
                            if result.returncode != 0:
                                log.warning("JACK disconnect failed %s -x- %s: %s",
                                            src_port, dst_port,
                                            (result.stderr or "").strip())
                        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                            log.warning("jack_disconnect command failed: %s", e)

                self._connections.remove(connection)
                self.mark_dirty()

                src_name = source.name if source else source_device
                dst_name = dest.name if dest else dest_device
                log.info("Audio connection removed: %s -> %s", src_name, dst_name)

                self._fire_on_change()

                return True
            else:
                log.warning("Connection not found: %s -> %s", source_device, dest_device)
                return False

        except Exception as e:
            log.error("Failed to remove audio connection: %s", e)
            return False

    async def remove_wire(self, src_port: str, dst_port: str) -> bool:
        """Remove exactly ONE port wire ({src: dst} within a stored
        connection), dropping the record when its last wire goes.

        The matrix UI toggles individual cells, i.e. individual jack
        wires — unlike disconnect_devices which removes a whole
        device-pair record and everything it carries.
        """
        import subprocess

        for conn in self._connections:
            mapping = conn.channel_mapping or {}
            if mapping.get(src_port) != dst_port:
                continue

            try:
                result = subprocess.run(
                    ["jack_disconnect", src_port, dst_port],
                    capture_output=True, text=True, timeout=5)
                if result.returncode != 0:
                    log.warning("jack_disconnect refused %s -x- %s: %s",
                                src_port, dst_port,
                                (result.stderr or "").strip())
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                log.warning("jack_disconnect failed for %s -x- %s: %s",
                            src_port, dst_port, e)

            mapping.pop(src_port, None)
            conn.channel_mapping = mapping
            self._connections.remove(conn)   # record dropped once empty of wires
            self.mark_dirty()
            log.info("Audio wire removed: %s -x- %s", src_port, dst_port)

            self._fire_on_change()
            return True

        log.warning("Wire not found in saved connections: %s -> %s",
                    src_port, dst_port)
        return False

    async def remove_connection(self, source_device: str, dest_device: str) -> bool:
        """Remove audio connection (API compatibility method)."""
        return await self.disconnect_devices(source_device, dest_device)

    def _auto_discover_port_mapping(self, source: AudioDevice, dest: AudioDevice) -> Dict:
        """Pair the source device's JACK output ports with the destination's
        input ports positionally (1->1, 2->2 ...), using REAL ports observed
        from jack_lsp — never synthesised names.

        A device may span several JACK clients (owner 'system', or one bridge
        per direction); ports from any of them qualify.

        Returns a dict of FULL port names {src_full_name: dst_full_name},
        sized to whichever side has fewer ports.
        """
        if not source.jack_client_names or not dest.jack_client_names:
            return {}

        source_outputs = sorted(
            p["name"] for p in self._jack_ports
            if p.get("direction") == "output"
            and p["name"].split(":", 1)[0] in source.jack_client_names)
        dest_inputs = sorted(
            p["name"] for p in self._jack_ports
            if p.get("direction") == "input"
            and p["name"].split(":", 1)[0] in dest.jack_client_names)

        n = min(len(source_outputs), len(dest_inputs))
        mapping = {}
        for i in range(n):
            mapping[source_outputs[i]] = dest_inputs[i]
        return mapping

    def _create_audio_device_from_alsa(self, alsa_device: dict) -> Optional[AudioDevice]:
        """Create AudioDevice from ALSA device information."""
        try:
            card_num = alsa_device["card"]
            device_name = alsa_device["name"]
            has_capture = alsa_device.get("has_capture", False)
            has_playback = alsa_device.get("has_playback", True)  # Most devices have playback

            # Generate stable device ID
            device_id = self._generate_stable_device_id(card_num, device_name, alsa_device)

            # Use USB info if available
            usb_topology = alsa_device.get("usb_path", "")
            serial = alsa_device.get("serial", "")

            # Get device capabilities
            sample_rates = self._get_device_sample_rates(card_num)
            channels = self._get_device_channels(card_num, has_capture, has_playback)

            # Generate appropriate input/output port names
            inputs = []
            outputs = []

            if has_capture:
                inputs = self._generate_port_names(card_num, "input", channels.get("input_count", 2))
            if has_playback:
                outputs = self._generate_port_names(card_num, "output", channels.get("output_count", 2))

            device = AudioDevice(
                device_id=device_id,
                name=device_name,
                inputs=inputs,
                outputs=outputs,
                sample_rates=sample_rates,
                channels=channels,
                usb_topology=usb_topology,
                serial=serial,
                jack_client_name=device_name.replace(" ", "_").replace("/", "_"),
                has_capture=has_capture,
                has_playback=has_playback
            )

            return device

        except Exception as e:
            log.warning("Failed to create AudioDevice from ALSA: %s", e)
            return None

    def _generate_port_names(self, card_num: int, direction: str, count: int) -> List[str]:
        """Generate JACK port names for a device."""
        ports = []
        for i in range(count):
            ports.append(f"{direction}_{i+1}")
        return ports

    def _generate_stable_device_id(self, card_num: int, device_name: str, alsa_device: dict = None) -> str:
        """Generate stable device ID from card number and name.

        Args:
            card_num: ALSA card number
            device_name: Device name from ALSA
            alsa_device: Full ALSA device dict (optional, for additional info)

        Returns:
            Stable device ID string
        """
        # Try to get USB serial number for truly stable ID
        serial = self._get_usb_serial(card_num)
        if serial:
            return f"audio-{device_name}-{serial}"

        # Try to use USB topology if available
        if alsa_device:
            usb_port = alsa_device.get("usb_port", "")
            if usb_port:
                return f"audio-{device_name.lower()}-usb{usb_port}"

        # Fallback: use card number and name (may change across reconnects)
        return f"audio-card{card_num}-{device_name.lower()}"

    def _extract_usb_topology(self, card_num: int) -> str:
        """Extract USB topology path for stable device identification."""
        try:
            # Check sysfs for USB device information
            card_path = Path(f"/sys/class/sound/card{card_num}")
            if card_path.exists():
                # Look for device symlink to get USB topology
                device_link = card_path / "device"
                if device_link.is_symlink():
                    target = device_link.resolve()
                    # Extract USB topology from path
                    # Path format: /sys/devices/pci0000:00/0000:00:14.0/usb1/1-3/...
                    parts = target.parts
                    usb_parts = [p for p in parts if p.startswith(("usb", "1-"))]
                    if usb_parts:
                        return "/".join(usb_parts[-2:])  # Last two parts give bus:port
        except Exception as e:
            log.warning("Failed to extract USB topology: %s", e)

        return ""

    def _get_usb_serial(self, card_num: int) -> str:
        """Get USB serial number for stable device identification."""
        try:
            # Check sysfs for USB device information
            card_path = Path(f"/sys/class/sound/card{card_num}")
            if card_path.exists():
                # Look for device symlink to get USB serial
                device_link = card_path / "device"
                if device_link.is_symlink():
                    # Try to read serial from uevent file
                    uevent_path = device_link / "uevent"
                    if uevent_path.exists():
                        uevent_content = uevent_path.read_text()
                        for line in uevent_content.splitlines():
                            if line.startswith("PRODUCT=") or line.startswith("SERIAL="):
                                # Extract unique identifier
                                parts = line.split("=")[1].split("/")
                                if len(parts) >= 2:
                                    return f"{parts[-2]}/{parts[-1]}" if "/" in line else parts[-1]
        except Exception as e:
            log.debug("Failed to get USB serial: %s", e)

        return ""

    def _get_device_sample_rates(self, card_num: int) -> List[int]:
        """Get supported sample rates for audio device."""
        # Common sample rates for USB audio
        return [44100, 48000, 88200, 96000]

    def _get_device_channels(self, card_num: int, has_capture: bool, has_playback: bool) -> Dict:
        """Get channel information for audio device."""
        channels = {}

        try:
            # Try to get channel info from ALSA
            card_path = Path(f"/sys/class/sound/card{card_num}")

            if has_capture:
                # Get input channel count
                input_count = 2  # Default fallback
                try:
                    # Check pcm files for capture
                    capture_files = list(card_path.glob("pcm*c"))
                    if capture_files:
                        # Parse info from pcm file name or contents
                        for pcm_file in capture_files:
                            if "c" in pcm_file.name:  # capture device
                                # Try to read channel info
                                info_file = pcm_file / "info"
                                if info_file.exists():
                                    info = info_file.read_text()
                                    if "channels:" in info.lower():
                                        for line in info.splitlines():
                                            if "channels:" in line.lower():
                                                input_count = int(line.split(":")[1].strip())
                                                break
                except Exception:
                    pass

                channels["input_count"] = input_count
                for i in range(input_count):
                    channels[f"input_{i+1}"] = {
                        "type": "input",
                        "rate": "hardware"
                    }

            if has_playback:
                # Get output channel count
                output_count = 2  # Default fallback
                try:
                    playback_files = list(card_path.glob("pcm*p"))
                    if playback_files:
                        for pcm_file in playback_files:
                            if "p" in pcm_file.name:  # playback device
                                info_file = pcm_file / "info"
                                if info_file.exists():
                                    info = info_file.read_text()
                                    if "channels:" in info.lower():
                                        for line in info.splitlines():
                                            if "channels:" in line.lower():
                                                output_count = int(line.split(":")[1].strip())
                                                break
                except Exception:
                    pass

                channels["output_count"] = output_count
                for i in range(output_count):
                    channels[f"output_{i+1}"] = {
                        "type": "output",
                        "rate": "hardware"
                    }

        except Exception as e:
            log.warning("Failed to get device channels: %s", e)

        # Fallback to stereo if we couldn't detect channels
        if not channels:
            channels = {
                "input_count": 2,
                "output_count": 2,
                "input_1": {"type": "input", "rate": "hardware"},
                "input_2": {"type": "input", "rate": "hardware"},
                "output_1": {"type": "output", "rate": "hardware"},
                "output_2": {"type": "output", "rate": "hardware"}
            }

        return channels

    def _notify_device_connected(self):
        """Notify callbacks about device discovery."""
        for callback in self._on_device_connected_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(self.devices))
                else:
                    callback(self.devices)
            except Exception as e:
                log.warning("Device connected callback failed: %s", e)

    def _cleanup(self):
        """Tear down the audio graph. Kills ONLY the helper processes this
        engine spawned (bridges first, then our jackd) — an externally
        started jackd is left untouched so we never yank someone else's rig.
        Clearing device state here also means a later start() rediscovers.
        """
        import subprocess

        log.info("Cleaning up AudioEngine resources")

        for name, proc in list(self._bridge_procs.items()):
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                log.info("Stopped bridge %s", name)
            except Exception as e:
                log.warning("Failed to stop bridge %s: %s", name, e)
        self._bridge_procs.clear()

        if self._jack_proc is not None:
            try:
                if self._jack_proc.poll() is None:
                    self._jack_proc.terminate()
                    try:
                        self._jack_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._jack_proc.kill()
                log.info("Stopped our jackd (PID %d)", self._jack_proc.pid)
            except Exception as e:
                log.warning("Failed to stop our jackd: %s", e)
            finally:
                self._jack_proc = None
                self._owner_card = None
        else:
            log.info("jackd was not ours — left running")

        # Clear device and connection state
        self._devices.clear()
        self._card_of_device.clear()
        self._jack_clients_by_card.clear()
        self._connections.clear()

    def _start_hotplug_monitoring(self):
        """Start monitoring for audio device hot-plug events."""
        try:
            self._hotplug_task = asyncio.create_task(self._monitor_audio_hotplug())
            log.info("Started audio device hot-plug monitoring")
        except Exception as e:
            log.warning("Failed to start hot-plug monitoring: %s", e)

    async def _monitor_audio_hotplug(self):
        """Monitor for audio device connect/disconnect events."""
        import asyncio
        from pathlib import Path

        cards_path = Path("/proc/asound/cards")

        while self._running:
            try:
                # Graph health first: if OUR jackd or a bridge died (e.g.
                # the USB card it held was unplugged), rebuild the whole
                # graph and re-wire saved connections. (_jack_proc is only
                # set when we spawned jackd ourselves; an external daemon
                # is nobody's business here.)
                if self._jack_proc is not None and self._jack_proc.poll() is not None:
                    log.warning("Our jackd exited (rc=%s)", self._jack_proc.returncode)
                    await self._rebuild_audio_graph()
                    continue
                if any(p.poll() is not None for p in self._bridge_procs.values()):
                    log.warning("A JACK bridge died — rebuilding audio graph")
                    await self._rebuild_audio_graph()
                    continue

                # Graph bring-up never succeeded (jackd could not bind, e.g.
                # its ALSA device was busy) — retry periodically instead of
                # dying forever. This also covers "the blocking process went
                # away" recovery without needing a replug or mode switch.
                if (self._jack_proc is None and not self._bridge_procs
                        and not self._jack_was_external
                        and time.monotonic() >= self._next_graph_retry):
                    self._next_graph_retry = time.monotonic() + 30.0
                    log.info("JACK graph absent — retrying audio graph "
                             "bring-up")
                    try:
                        self._initialize_jack()
                        self._discover_audio_devices()
                        self._restore_saved_connections()
                    except Exception:
                        log.exception("Audio graph retry failed")

                # Check if devices have changed
                current_state = self._get_current_device_state()

                # Compare with previous state
                new_devices = set(current_state.keys()) - set(self._last_device_state.keys())
                removed_devices = set(self._last_device_state.keys()) - set(current_state.keys())

                if new_devices:
                    log.info("New audio devices detected: %s", new_devices)
                    await self._handle_device_addition(new_devices)

                if removed_devices:
                    log.info("Audio devices removed: %s", removed_devices)
                    await self._handle_device_removal(removed_devices)

                # Update state for next iteration
                self._last_device_state = current_state

                # Wait before next check (don't poll too frequently)
                await asyncio.sleep(2)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Error in hot-plug monitoring: %s", e)
                await asyncio.sleep(5)  # Wait longer on error

    async def _rebuild_audio_graph(self):
        """Full graph rebuild after our jackd or a bridge died (usually
        because its USB card was yanked). Runs blocking work inline — this
        is a rare recovery path, not a steady-state cost."""
        log.warning("Rebuilding audio graph")
        for name, proc in self._bridge_procs.items():
            state = (f"exited rc={proc.returncode}"
                     if proc.poll() is not None else "still running")
            log.warning("Discarding bridge '%s' (%s)%s", name, state,
                        self._read_err_tail(self._bridge_errfiles.get(name)))
        for errf in self._bridge_errfiles.values():
            try:
                errf.close()
            except Exception:
                pass
        self._bridge_errfiles.clear()
        self._bridge_procs.clear()
        if self._jack_errfile is not None and self._jack_proc is not None \
                and self._jack_proc.poll() is not None:
            log.warning("Old jackd rc=%s%s", self._jack_proc.returncode,
                        self._read_err_tail(self._jack_errfile))
        if self._jack_errfile is not None:
            try:
                self._jack_errfile.close()
            except Exception:
                pass
            self._jack_errfile = None
        self._jack_proc = None
        self._owner_card = None
        try:
            await asyncio.sleep(1.0)   # let the kernel settle the USB removal
            self._initialize_jack()
            self._discover_audio_devices()
            self._restore_saved_connections()
            log.info("Audio graph rebuilt with %d device(s)", len(self._devices))
        except Exception:
            log.exception("Audio graph rebuild failed")

    def _get_current_device_state(self) -> Dict[str, bool]:
        """Set of stable device ids present RIGHT NOW.

        Keyed by the SAME device_id generation the discovery uses, so the
        hotplug diff survives card-number churn (an unplug/replug cycle
        typically moves the gadget to a different ALSA card number).
        The previous card-number-string parse leaked garbage keys from
        the description lines and never matched, stacking up duplicate
        entries in _devices on every replug.
        """
        state = {}
        try:
            for d in self._scan_alsa_devices():
                dev = self._create_audio_device_from_alsa(d)
                if dev:
                    state[dev.device_id] = True
        except Exception as e:
            log.warning("Failed to get device state: %s", e)
        return state

    async def _handle_device_addition(self, new_devices: set):
        """Integrate newly-seen devices.

        Brings graph coverage up to date (a fresh card needs its
        alsa_in/alsa_out bridges spawned), re-runs discovery, then re-wires
        whatever saved connections now have both ends online. Safe when the
        graph was never up — every step no-ops or retries honestly then.
        """
        try:
            if self._server_reachable() and self._owner_card is not None:
                self._bridge_secondary_cards(self._scan_alsa_devices(),
                                             self._owner_card)

            # Re-registers everything under stable ids (replaces rather
            # than duplicates) and fires the connected callbacks itself.
            self._discover_audio_devices()

            self._restore_saved_connections()
            self.mark_dirty()
        except Exception as e:
            log.error("Failed to handle device addition: %s", e)

    async def _handle_device_removal(self, removed_devices: set):
        """Forget devices whose stable ids vanished, plus any connections
        that referenced them."""
        removed_count = 0
        try:
            for device_id in list(self._devices.keys()):
                if device_id not in removed_devices:
                    continue

                device = self._devices.pop(device_id)
                self._card_of_device.pop(device_id, None)

                # Drop connections involving this device
                self._connections = [
                    conn for conn in self._connections
                    if conn.source_device != device_id
                    and conn.dest_device != device_id
                ]

                removed_count += 1
                log.info("Removed audio device: %s", device.name)

                for callback in self._on_device_disconnected_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(device_id)
                        else:
                            callback(device_id)
                    except Exception as e:
                        log.warning("Device disconnected callback failed: %s", e)

            if removed_count > 0:
                self.mark_dirty()
        except Exception as e:
            log.error("Failed to handle device removal: %s", e)

    def on_device_connected(self, callback: Callable):
        """Register callback for device connection events."""
        self._on_device_connected_callbacks.append(callback)

    def on_device_disconnected(self, callback: Callable):
        """Register callback for device disconnection events."""
        self._on_device_disconnected_callbacks.append(callback)

    # Callback registration methods (MidiEngine compatibility)
    def on_change(self, callback: Callable):
        """Register callback for routing changes."""
        self._on_change_callbacks.append(callback)

    def on_midi_event(self, callback: Callable):
        """Register callback for audio events (compatibility)."""
        self._on_midi_event_callbacks.append(callback)

    def on_transport_start(self, callback: Callable):
        """Register callback for transport start (compatibility)."""
        self._on_transport_start_callbacks.append(callback)

    def mark_dirty(self):
        """Mark configuration as dirty (for autosave)."""
        self._dirty = True

    def clear_dirty(self):
        """Clear dirty flag."""
        self._dirty = False

    # Configuration methods
    def _load_audio_routing_config(self, config: dict):
        """Load audio routing configuration from config dict."""
        audio_routing = config.get("audio_routing", {})
        connections_data = audio_routing.get("connections", [])
        devices_data = audio_routing.get("devices", {})

        # Restore connections
        for conn_data in connections_data:
            conn = AudioConnection(
                source_device=conn_data.get("source", ""),
                dest_device=conn_data.get("dest", ""),
                channel_mapping=conn_data.get("channel_mapping", {}),
                enabled=conn_data.get("enabled", True),
                gain=conn_data.get("gain", {}),
                muted=conn_data.get("muted", False),
                phase_invert=conn_data.get("phase_invert", False)
            )
            self._connections.append(conn)

        log.info("Loaded %d audio connections from config", len(self._connections))

    def _save_audio_routing_config(self, config: dict):
        """Save audio routing configuration to config dict."""
        if "audio_routing" not in config:
            config["audio_routing"] = {}

        config["audio_routing"]["connections"] = [
            {
                "source": conn.source_device,
                "dest": conn.dest_device,
                "channel_mapping": conn.channel_mapping,
                "enabled": conn.enabled,
                "gain": conn.gain,
                "muted": conn.muted,
                "phase_invert": conn.phase_invert
            }
            for conn in self._connections
        ]

        config["audio_routing"]["devices"] = {
            device_id: {
                "name": device.name,
                "usb_topology": device.usb_topology,
                "serial": device.serial,
                "jack_client_name": device.jack_client_name
            }
            for device_id, device in self._devices.items()
        }

        log.info("Saved %d audio connections to config", len(self._connections))

    # Compatibility methods for existing codebase
    def _scan_and_connect(self):
        """Scan devices and restore saved connections (MidiEngine compatibility)."""
        try:
            if self._config:
                self._load_audio_routing_config(self._config.data)
                self._restore_saved_connections()
        except Exception as e:
            log.error("Failed to scan and connect: %s", e)

    def _restore_saved_connections(self):
        """Restore saved audio connections.

        A saved channel_mapping of FULL jack port names is authoritative —
        the matrix UI wires exactly the cells the user ticked, and a
        positional auto-discovery here would resurrect channels they left
        out. Full names also survive card-number churn: ports are matched
        by name via the live graph, so only genuinely-absent endpoints
        fail (logged), never re-pair onto different ports. Legacy entries
        written by the old name-synthesis code ("out_1") carry no usable
        names and fall back to positional auto-discovery.
        """
        import subprocess
        if not self._connections:
            return

        log.info("Restoring %d saved audio connections", len(self._connections))
        restored_count = 0

        for connection in self._connections:
            if connection.source_device in self._devices and connection.dest_device in self._devices:
                source = self._devices[connection.source_device]
                dest = self._devices[connection.dest_device]
                try:
                    mapping = connection.channel_mapping or {}
                    if mapping and all(
                            ":" in k and ":" in v
                            for k, v in mapping.items()):
                        port_map = dict(mapping)
                    else:
                        port_map = self._auto_discover_port_mapping(source, dest)
                    for src_port, dst_port in port_map.items():
                        try:
                            result = subprocess.run(
                                ["jack_connect", src_port, dst_port],
                                capture_output=True, text=True, timeout=5
                            )
                            if result.returncode == 0:
                                restored_count += 1
                        except (FileNotFoundError, subprocess.TimeoutExpired):
                            pass  # device may still be settling at boot

                    # Cache the live port names so delete works without a rescan.
                    if port_map:
                        connection.channel_mapping = dict(port_map)
                    connection.enabled = True

                except Exception as e:
                    log.warning("Failed to restore connection %s -> %s: %s",
                               connection.source_device, connection.dest_device, e)

        log.info("Restored %d audio connections", restored_count)

    def switch_mode(self, new_mode: str):
        """Switch operating mode (EngineManager compatibility)."""
        log.info("Switching to %s mode from AudioEngine", new_mode)
        # This will be called by EngineManager when switching modes
        # AudioEngine doesn't need to do anything special here

    @property
    def monitor_port(self):
        """Compatibility property for MidiEngine interface."""
        return self._monitor_port

    def snapshot_rates(self) -> Dict:
        """Return event rates for monitoring (MidiEngine compatibility)."""
        # Audio engine doesn't have the same event rate structure as MIDI
        # Return empty dict for compatibility
        return {}

    def cc_dest_snapshot_dirty(self) -> Dict:
        """Return CC destination snapshot dirty state (MidiEngine compatibility)."""
        # Audio engine doesn't use CC destinations like MIDI
        # Return empty dict for compatibility
        return {}