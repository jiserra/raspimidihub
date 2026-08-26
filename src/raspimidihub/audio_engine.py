"""Audio routing engine for USB audio interfaces via JACK.

This module provides audio routing capabilities similar to how MidiEngine
handles MIDI routing, but for USB audio interfaces using the JACK Audio
Connection Kit.
"""

import asyncio
import logging
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
    jack_client_name: str = ""  # JACK client name

    def __post_init__(self):
        if self.inputs is None:
            self.inputs = []
        if self.outputs is None:
            self.outputs = []
        if self.sample_rates is None:
            self.sample_rates = [44100, 48000]  # Common rates
        if self.channels is None:
            self.channels = {}


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

        # Audio routing settings
        self._sample_rate = 48000
        self._buffer_size = 128

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
        """Initialize JACK client connection and start JACK server if needed."""
        log.info("Initializing JACK client: %s", self._client_name)

        try:
            # First, check if JACK daemon is already running
            import subprocess
            try:
                result = subprocess.run(["jack_lsp"], capture_output=True, timeout=2)
                jack_running = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                jack_running = False

            if not jack_running:
                log.info("JACK daemon not running, starting JACK server")
                self._start_jack_server()

            # TODO: Initialize JACK client when Python JACK bindings are available
            # For now, we'll use command-line tools (jack_connect, jack_disconnect, etc.)
            log.info("JACK ready for audio routing")

        except Exception as e:
            log.error("Failed to initialize JACK: %s", e)
            raise

    def _start_jack_server(self, preferred_device: str = None):
        """Start JACK server with appropriate parameters.

        Args:
            preferred_device: Optional ALSA device (e.g., "hw:3") to use
        """
        try:
            import subprocess

            # Find the best audio device to use for JACK
            # Priority: USB audio interfaces > built-in audio
            target_device = preferred_device or self._find_best_audio_device()

            if not target_device:
                log.warning("No suitable audio device found, using hw:0")
                target_device = "hw:0"
            else:
                log.info("Using audio device: %s", target_device)

            # Start JACK daemon with standard parameters
            cmd = [
                "jackd", "-d", "alsa",
                "-d", target_device,  # Use the best available device
                "-r", "48000",        # Sample rate
                "-p", "128",          # Buffer size
                "-n", "3",            # Periods
                "--name", self._client_name
            ]

            log.info("Starting JACK server: %s", " ".join(cmd))

            # Start JACK daemon in background
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True  # Detach from parent process
            )

            # Wait a moment for JACK to start
            import time
            time.sleep(2)

            # Check if JACK started successfully
            if process.poll() is not None:
                # Process has exited
                stderr = process.stderr.read().decode() if process.stderr else ""
                log.error("JACK daemon failed to start: %s", stderr)
                raise RuntimeError("JACK daemon startup failed")

            log.info("JACK server started successfully (PID: %d)", process.pid)

        except Exception as e:
            log.error("Failed to start JACK server: %s", e)
            raise

    def _find_best_audio_device(self) -> Optional[str]:
        """Find the best audio device for JACK to use.

        Priority: USB audio interfaces > built-in audio
        Returns ALSA device string like "hw:3"
        """
        try:
            devices = self._scan_alsa_devices()

            # Look for USB audio devices first
            for device in devices:
                device_name = device.get("name", "").lower()
                # Check if it's a USB audio device
                card_num = device.get("card")
                card_path = Path(f"/sys/class/sound/card{card_num}")

                if card_path.exists():
                    # Check if it's a USB device
                    device_link = card_path / "device"
                    if device_link.is_symlink():
                        target = device_link.resolve()
                        # USB devices have "usb" in their path
                        if "usb" in str(target).lower():
                            log.info("Found USB audio device: %s (card %s)", device.get("name"), card_num)
                            return f"hw:{card_num}"

            # Fallback to first available device
            if devices:
                card_num = devices[0].get("card")
                log.info("Using first available device: card %s", card_num)
                return f"hw:{card_num}"

        except Exception as e:
            log.warning("Failed to find best audio device: %s", e)

        return None

    def _scan_alsa_devices(self) -> List[dict]:

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

            # Discover JACK ports (if JACK client is active)
            if self._jack_client:
                jack_ports = self._scan_jack_ports()
                log.info("Found %d JACK ports", len(jack_ports))

            # Create AudioDevice objects from discovered hardware
            for alsa_device in alsa_devices:
                device = self._create_audio_device_from_alsa(alsa_device)
                if device:
                    self._devices[device.device_id] = device
                    log.info("Registered audio device: %s (%s)", device.name, device.device_id)

            # Notify callbacks
            self._notify_device_connected()

        except Exception as e:
            log.error("Audio device discovery failed: %s", e)

    def _scan_alsa_devices(self) -> List[dict]:
        """Scan for ALSA audio devices from /proc/asound."""
        devices = []
        try:
            cards_path = Path("/proc/asound/cards")
            if not cards_path.exists():
                log.warning("ALSA cards file not found")
                return devices

            card_lines = cards_path.read_text().splitlines()
            for line in card_lines:
                if not line.strip():
                    continue

                # Parse line format: "0 [MIDI    ]: USB-MIDI"
                parts = line.split(":")
                if len(parts) >= 2:
                    card_num = int(parts[0].strip())
                    name_part = parts[1].strip()

                    # Extract card name from brackets
                    if "[" in name_part and "]" in name_part:
                        name = name_part.split("[")[1].split("]")[0].strip()
                    else:
                        name = name_part.split()[0].strip()

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
        """Scan for JACK audio ports."""
        ports = []
        try:
            # Check if JACK is running
            import subprocess
            result = subprocess.run(["jack_lsp"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.strip():
                        ports.append({
                            "name": line.strip(),
                            "type": "audio"  # Default to audio for now
                        })
                log.info("Found %d JACK ports via jack_lsp", len(ports))
            else:
                log.info("JACK daemon not running or no ports available")

        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning("Failed to scan JACK ports: %s", e)

        return ports

    async def connect_devices(self, source_device: str, dest_device: str,
                             channel_mapping: Dict = None) -> bool:
        """Create audio connection between devices via JACK.

        Args:
            source_device: Source device ID
            dest_device: Destination device ID
            channel_mapping: Optional channel mapping {"out:1": "in:1", ...}

        Returns:
            True if connection successful, False otherwise
        """
        if source_device not in self._devices or dest_device not in self._devices:
            log.error("Unknown device in connection request")
            return False

        source = self._devices[source_device]
        dest = self._devices[dest_device]

        try:
            # Create AudioConnection object
            connection = AudioConnection(
                source_device=source_device,
                dest_device=dest_device,
                channel_mapping=channel_mapping or {},
                enabled=True
            )

            # TODO: Implement actual JACK connections
            # For now, use jack_connect command-line tool
            if channel_mapping:
                for source_ch, dest_ch in channel_mapping.items():
                    source_port = f"{source.jack_client_name}:{source_ch}"
                    dest_port = f"{dest.jack_client_name}:{dest_ch}"

                    # Try to connect via jack_connect
                    try:
                        import subprocess
                        result = subprocess.run(
                            ["jack_connect", source_port, dest_port],
                            capture_output=True, text=True, timeout=5
                        )
                        if result.returncode != 0:
                            log.warning("JACK connect failed: %s", result.stderr)
                    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                        log.warning("jack_connect command failed: %s", e)
            else:
                # Default: connect all available channels
                log.info("Creating default audio connection: %s -> %s", source.name, dest.name)

            self._connections.append(connection)
            self.mark_dirty()

            log.info("Audio connection created: %s -> %s", source.name, dest.name)

            # Notify callbacks
            for callback in self._on_change_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        asyncio.create_task(callback())
                    else:
                        callback()
                except Exception as e:
                    log.warning("Connection change callback failed: %s", e)

            return True

        except Exception as e:
            log.error("Failed to create audio connection: %s", e)
            return False

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
                # TODO: Implement actual JACK disconnections
                # For now, use jack_disconnect command-line tool
                source = self._devices[source_device]
                dest = self._devices[dest_device]

                if connection.channel_mapping:
                    for source_ch, dest_ch in connection.channel_mapping.items():
                        source_port = f"{source.jack_client_name}:{source_ch}"
                        dest_port = f"{dest.jack_client_name}:{dest_ch}"

                        try:
                            import subprocess
                            result = subprocess.run(
                                ["jack_disconnect", source_port, dest_port],
                                capture_output=True, text=True, timeout=5
                            )
                            if result.returncode != 0:
                                log.warning("JACK disconnect failed: %s", result.stderr)
                        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                            log.warning("jack_disconnect command failed: %s", e)

                self._connections.remove(connection)
                self.mark_dirty()

                log.info("Audio connection removed: %s -> %s", source.name, dest.name)

                # Notify callbacks
                for callback in self._on_change_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            asyncio.create_task(callback())
                        else:
                            callback()
                    except Exception as e:
                        log.warning("Connection change callback failed: %s", e)

                return True
            else:
                log.warning("Connection not found: %s -> %s", source_device, dest_device)
                return False

        except Exception as e:
            log.error("Failed to remove audio connection: %s", e)
            return False

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
                jack_client_name=device_name.replace(" ", "_").replace("/", "_")
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

    def _generate_stable_device_id(self, card_num: int, device_name: str, alsa_device: dict) -> str:
        """Generate stable device ID from card number, name, and USB info."""
        # Try to get USB serial number for truly stable ID
        serial = alsa_device.get("serial", "")
        if serial:
            return f"audio-{device_name.lower()}-{serial}"

        # Try to use USB topology as fallback
        usb_port = alsa_device.get("usb_port", "")
        if usb_port:
            return f"audio-{device_name.lower()}-usb{usb_port}"

        # Fallback: use card number and name (may change across reconnects)
        return f"audio-card{card_num}-{device_name.lower()}"

    def _generate_stable_device_id(self, card_num: int, device_name: str) -> str:
        """Generate stable device ID from card number and name."""
        # Try to get USB serial number for truly stable ID
        serial = self._get_usb_serial(card_num)
        if serial:
            return f"audio-{device_name}-{serial}"

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
        """Clean up JACK client and resources."""
        log.info("Cleaning up AudioEngine resources")

        # Stop JACK daemon
        try:
            import subprocess
            # Try to gracefully stop JACK
            subprocess.run(["jack_kill", "-9"], capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # JACK may not be running or jack_kill not available

        # Clear device and connection state
        self._devices.clear()
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

    def _get_current_device_state(self) -> Dict[str, bool]:
        """Get current state of audio devices."""
        state = {}
        try:
            cards_path = Path("/proc/asound/cards")
            if cards_path.exists():
                for line in cards_path.read_text().splitlines():
                    if line.strip():
                        # Extract card number
                        parts = line.split(":")
                        if parts:
                            card_num = parts[0].strip()
                            state[card_num] = True
        except Exception as e:
            log.warning("Failed to get device state: %s", e)

        return state

    async def _handle_device_addition(self, new_devices: set):
        """Handle addition of new audio devices."""
        try:
            # Re-scan devices to pick up new hardware
            old_device_count = len(self._devices)
            self._discover_audio_devices()
            new_device_count = len(self._devices)

            if new_device_count > old_device_count:
                log.info("Added %d new audio device(s)", new_device_count - old_device_count)

                # Notify callbacks
                for callback in self._on_device_connected_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(self.devices)
                        else:
                            callback(self.devices)
                    except Exception as e:
                        log.warning("Device connected callback failed: %s", e)

                # Mark config as dirty for autosave
                self.mark_dirty()

        except Exception as e:
            log.error("Failed to handle device addition: %s", e)

    async def _handle_device_removal(self, removed_devices: set):
        """Handle removal of audio devices."""
        try:
            # Remove devices that are no longer present
            removed_count = 0
            for device_id, device in list(self._devices.items()):
                # Check if device is still present
                device_card_num = device.device_id.split("card")[1].split("-")[0] if "card" in device.device_id else None
                if device_card_num and device_card_num in removed_devices:
                    # Remove connections involving this device
                    self._connections = [
                        conn for conn in self._connections
                        if conn.source_device != device_id and conn.dest_device != device_id
                    ]

                    # Remove device
                    del self._devices[device_id]
                    removed_count += 1
                    log.info("Removed audio device: %s", device.name)

                    # Notify callbacks
                    for callback in self._on_device_disconnected_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(device_id)
                            else:
                                callback(device_id)
                        except Exception as e:
                            log.warning("Device disconnected callback failed: %s", e)

            if removed_count > 0:
                # Mark config as dirty for autosave
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
        """Restore saved audio connections."""
        if not self._connections:
            return

        log.info("Restoring %d saved audio connections", len(self._connections))
        restored_count = 0

        for connection in self._connections:
            if connection.source_device in self._devices and connection.dest_device in self._devices:
                try:
                    # Re-establish JACK connections for saved connection
                    source = self._devices[connection.source_device]
                    dest = self._devices[connection.dest_device]

                    if connection.channel_mapping:
                        for source_ch, dest_ch in connection.channel_mapping.items():
                            source_port = f"{source.jack_client_name}:{source_ch}"
                            dest_port = f"{dest.jack_client_name}:{dest_ch}"

                            try:
                                import subprocess
                                result = subprocess.run(
                                    ["jack_connect", source_port, dest_port],
                                    capture_output=True, text=True, timeout=5
                                )
                                if result.returncode == 0:
                                    restored_count += 1
                            except (FileNotFoundError, subprocess.TimeoutExpired):
                                pass  # May fail if device not yet available

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