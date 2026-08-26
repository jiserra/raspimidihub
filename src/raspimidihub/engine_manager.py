"""Engine manager for dynamic switching between MIDI and Audio routing engines."""

import asyncio
import logging
from typing import Optional, Callable

log = logging.getLogger(__name__)


class EngineManager:
    """Manages dynamic switching between MIDI and Audio routing engines.

    This allows the system to switch between MIDI and Audio modes without
    requiring a system restart. Engines are cleanly stopped and started
    with proper resource cleanup.
    """

    def __init__(self):
        self._current_engine: Optional[object] = None
        self._current_mode: str = None  # Changed from "midi" to None
        self._mode_change_callbacks: list = []
        self._initial_startup = True  # Track if this is first startup

    @property
    def current_mode(self) -> str:
        """Current operating mode ('midi' or 'audio')."""
        return self._current_mode

    @property
    def current_engine(self) -> object:
        """Current active engine instance."""
        return self._current_engine

    def register_mode_change_callback(self, callback: Callable):
        """Register a callback to be called when mode changes."""
        self._mode_change_callbacks.append(callback)

    async def switch_mode(self, new_mode: str, engine_factory: Callable, **factory_kwargs):
        """Switch to a new operating mode.

        Args:
            new_mode: 'midi' or 'audio'
            engine_factory: Callable that creates the appropriate engine
            **factory_kwargs: Additional arguments to pass to engine_factory

        Raises:
            ValueError: If new_mode is not 'midi' or 'audio'
            RuntimeError: If mode switch fails
        """
        if new_mode not in ("midi", "audio"):
            raise ValueError("Mode must be 'midi' or 'audio'")

        # Handle initial startup (no current mode)
        if self._current_mode is None and self._initial_startup:
            log.info("Initial startup in %s mode", new_mode)
            try:
                self._current_engine = await self._start_engine(engine_factory, new_mode, **factory_kwargs)
                self._current_mode = new_mode
                self._initial_startup = False
                log.info("Successfully started in %s mode", new_mode)
                return
            except Exception as e:
                log.error("Failed to start %s engine: %s", new_mode, e)
                raise

        if new_mode == self._current_mode and not self._initial_startup:
            log.info("Already in %s mode, no switch needed", new_mode)
            return

        old_mode = self._current_mode
        log.info("Switching from %s to %s mode", old_mode, new_mode)

        try:
            # Stop current engine if exists
            if self._current_engine is not None:
                log.info("Stopping %s engine", old_mode)
                await self._stop_engine(self._current_engine)

            # Create and start new engine
            log.info("Starting %s engine", new_mode)
            self._current_engine = await self._start_engine(engine_factory, new_mode, **factory_kwargs)
            self._current_mode = new_mode

            # Notify callbacks
            for callback in self._mode_change_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(new_mode, self._current_engine)
                    else:
                        callback(new_mode, self._current_engine)
                except Exception as e:
                    log.warning("Mode change callback failed: %s", e)

            log.info("Successfully switched to %s mode", new_mode)

        except Exception as e:
            log.error("Failed to switch from %s to %s: %s", old_mode, new_mode, e)
            # Try to restore old engine
            try:
                if self._current_engine is not None:
                    await self._stop_engine(self._current_engine)
                self._current_engine = await self._start_engine(engine_factory, old_mode, **factory_kwargs)
                self._current_mode = old_mode
            except Exception as restore_error:
                log.error("Failed to restore %s mode after failed switch: %s", old_mode, restore_error)

            raise RuntimeError(f"Mode switch failed: {str(e)}") from e

    async def _stop_engine(self, engine: object):
        """Stop an engine cleanly."""
        try:
            # Call stop() if available
            if hasattr(engine, 'stop'):
                engine.stop()
            # Call async stop if available
            if hasattr(engine, 'astop'):
                await engine.astop()
            # Wait for event loop to stop if it's a MidiEngine-like object
            if hasattr(engine, '_event_loop_task'):
                task = engine._event_loop_task
                if task and not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass
        except Exception as e:
            log.warning("Error stopping engine: %s", e)

    async def _start_engine(self, factory: Callable, mode: str, **kwargs) -> object:
        """Start an engine."""
        try:
            engine = factory(mode, **kwargs)

            # Call start() if available
            if hasattr(engine, 'start'):
                engine.start()

            return engine
        except Exception as e:
            log.error("Failed to start %s engine: %s", mode, e)
            raise

    def get_engine(self):
        """Get the current engine instance."""
        return self._current_engine

    async def shutdown(self):
        """Clean shutdown of the current engine."""
        if self._current_engine is not None:
            await self._stop_engine(self._current_engine)
            self._current_engine = None