"""External Archipelago runtime for the full-network RomFS mod.

Uses the adapted OotrR Windows/Linux memory backend, native mailbox and tracker.
Only automatically observed game checks are sent: a manual tracker tick does not
become a network check. Reception requires the game's native readiness publisher
and rechecks pause/loading/active events, keeping unknown layouts closed.
"""
from pathlib import Path
import threading
import time
import unicodedata

from ootrr_full.archipelago.client import ArchipelagoClient
from ootrr_full.archipelago.receive import Deliverer, LiveDelivery, RETRY_SECONDS
from ootrr_full.patching.soul_adapter import murmur3
from ootrr_full.tracker import live_memory
from .upgrade_readiness import PAUSE, LOADING
from .i18n import tr


class SynchronizedLive:
    """One process attachment shared by tracker and item-delivery threads."""
    def __init__(self, live=None):
        self.live = live if live is not None else live_memory.LiveGameData()
        self.lock = threading.RLock()

    def __getattr__(self, name):
        return getattr(self.live, name)

    def snapshot(self):
        with self.lock:
            return self.live.snapshot()

    def close(self):
        with self.lock:
            self.live.memory.close()


class OrderedDeliverer(Deliverer):
    """Wait for the first uncommitted reward instead of reordering the history."""
    def step(self, keys, bools, now):
        pending = self.pending(keys, bools)
        if not pending:
            self.in_flight = None
            return None
        head = pending[0]
        if any(bools.get(self.recv[key]) is True for key in pending):
            return None
        if self.in_flight == head and now - self.sent_at < RETRY_SECONDS:
            return None
        self.in_flight, self.sent_at = head, now
        self.signals[head] = self.signals.get(head, 0) + 1
        return head


class SafeLiveDelivery(LiveDelivery):
    def __init__(self, manifest, live=None, *, readiness_flag=None, event_state=None, clock=time.monotonic):
        shared = live if isinstance(live, SynchronizedLive) else SynchronizedLive(live)
        super().__init__(manifest, live=shared, clock=clock)
        metadata = manifest.get("external_readiness") or (manifest.get("archipelago") or {}).get("readiness") or {}
        flag = readiness_flag or (metadata.get("flag") if isinstance(metadata, dict) else metadata)
        self.readiness_version = metadata.get('version') if isinstance(metadata, dict) else None
        self.readiness = murmur3(flag) if isinstance(flag, str) and flag.startswith("Archipelago.Ready.") else None
        self.events = event_state or live_memory.LiveEventState(memory=shared.memory)
        self.deliverer = OrderedDeliverer(self.records, murmur3)
        recovery = manifest.get('external_recovery') or {}
        self.session = murmur3(recovery['session_flag']) if recovery.get('session_flag') else None
        self.spent = {murmur3(record['spent']): record['consumed_by_location_id']
                      for record in self.records if record.get('spent')}
        self._confirmed = None
        deathlink = manifest.get('external_deathlink') or {}
        death_flags = deathlink.get('flags') or {}
        self.death_gate = tuple(murmur3(death_flags[name]) for name in ('dead', 'request', 'fired') if name in death_flags)

    def confirm_checks(self, checked):
        """Called only after Connected validates the exact room, token and catalog."""
        with self.live.lock:
            self._confirmed = frozenset(int(value) for value in checked)

    def suspend(self):
        """Close the native session gate while disconnected; retain pending items."""
        with self.live.lock:
            self._confirmed = None
            if self.session is None:
                return
            try:
                flags = self.live.snapshot()['bool']
                if flags.get(self.marker) is True and flags.get(self.session) is True:
                    live_memory.set_bool_in(self.live, self.session, False)
            except (OSError, live_memory.LiveUnavailable):
                pass

    def step(self, keys):
        with self.live.lock:
            if self.readiness is None:
                self.status = "item delivery needs the full-network mod's native readiness gate"
                return None
            try:
                flags = self.live.snapshot()["bool"]
                self.waiting = len(self.deliverer.pending(keys, flags))
                required = set(self.deliverer.recv.values()) | set(self.deliverer.got.values())
                required.update(self.death_gate)
                if self.signal is not None:
                    required.add(self.signal)
                if self.session is not None:
                    required.add(self.session)
                    required.update(self.spent)
                if not required <= flags.keys():
                    self.status = "native mailbox flags unavailable; check the prepared game version"
                    return None
                if any(flags[key] for key in self.death_gate):
                    self.status = 'waiting for the native DeathLink request to finish'
                    return None
                if self.session is not None:
                    if self._confirmed is None or flags.get(self.marker) is not True:
                        self.status = 'waiting for authenticated room state and this seed'
                        return None
                    for flag, location_id in self.spent.items():
                        value = location_id in self._confirmed
                        if flags[flag] is not value:
                            if not live_memory.set_bool_in(self.live, flag, value):
                                raise live_memory.LiveUnavailable('the trade replay flag is missing')
                if (flags.get(self.readiness) is not True or flags.get(murmur3(PAUSE)) is not False
                        or flags.get(murmur3(LOADING)) is not False or self.events.playing()):
                    self.status = ("Prepare this room again to update its native receipt safety gate."
                                   if self.readiness_version == 1 and flags.get(self.readiness) is False
                                   and flags.get(murmur3(PAUSE)) is False and flags.get(murmur3(LOADING)) is False
                                   and not self.events.playing() else "waiting for normal player control")
                    return None
                if self.session is not None and flags.get(self.session) is not True:
                    if not live_memory.set_bool_in(self.live, self.session, True):
                        raise live_memory.LiveUnavailable('the external session readiness flag is missing')
            except live_memory.LiveUnavailable as error:
                self.status = "game readiness unavailable (" + str(error) + ")"
                return None
            return super().step(keys)


class ExternalRuntime:
    """Lifecycle owned by the application; construction opens no process/network."""
    def __init__(self, directory, address, *, save_path, password="", slot=None,
                 on_change=None, local_data=None, live=None, connect=None, poll_seconds=1.0,
                 executable=None):
        from ootrr_full.randomizer.randomizer_services import read_artifact
        from ootrr_full.tracker.auto_tracker import TrackerSession
        self.directory = Path(directory)
        manifest, _ = read_artifact(self.directory)
        self.on_change = on_change or (lambda: None)
        if live is None and executable:
            live = live_memory.LiveGameData(memory=live_memory.process_memory(executable))
        self.live = live if isinstance(live, SynchronizedLive) else SynchronizedLive(live)
        self.delivery = SafeLiveDelivery(manifest, self.live)
        info = manifest.get("archipelago") or {}
        selected_slot = slot or info.get("slot_name") or "Link"
        from .upgrade_deathlink import ExternalDeathLink
        self.deathlink = ExternalDeathLink(manifest, self.live, event_state=self.delivery.events, slot=selected_slot)
        self.tracker = TrackerSession(self.directory, selected_slot, save_path=str(save_path), live=self.live,
                                      manual_directory=Path(local_data) if local_data else self.directory / ".tracker")
        self.client = ArchipelagoClient(manifest, address, password=password, slot=slot,
                                         on_change=self.on_change, connect=connect, delivery=self.delivery,
                                         deathlink=self.deathlink)
        self._stop = threading.Event()
        self._thread = None
        self._death_thread = None
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.status = "Not connected"

    def start(self):
        if self._thread is None:
            self.client.start()
            self._thread = threading.Thread(target=self._poll, name="archipelago-tracker", daemon=True)
            self._thread.start()
            if self.deathlink.enabled:
                self._death_thread = threading.Thread(target=self._poll_death, name="archipelago-deathlink", daemon=True)
                self._death_thread.start()

    def _poll_death(self):
        while not self._stop.wait(0.1):
            with self.client._lock:
                authenticated = self.client.connected and self.client._history_synced
                epoch = self.client._connection_epoch
            try:
                packet = self.deathlink.step(authenticated)
            except Exception as error:  # keep an unavailable game mailbox closed
                self.deathlink.suspend()
                self.deathlink.status = 'DeathLink unavailable (' + str(error) + ')'
                continue
            if packet is not None:
                with self.client._lock:
                    if (authenticated and self.client.connected and self.client._history_synced
                            and self.client._connection_epoch == epoch):
                        self.client._outbox.append(packet)
                self.client._wake.set()

    def _poll(self):
        while not self._stop.is_set():
            try:
                self.tracker.refresh()
                self.client.update(self.tracker.observed_completed, self.tracker.goal_reached)
                self.status = self.client.summary()["status"]
            except (OSError, ValueError, live_memory.LiveUnavailable) as error:
                self.status = "tracking unavailable (" + str(error) + ")"
            self.on_change()
            self._stop.wait(self.poll_seconds)

    def stop(self):
        self._stop.set()
        self.client.stop()
        self.delivery.suspend()
        self.deathlink.suspend()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self._death_thread is not None:
            self._death_thread.join(timeout=3)
        self.live.close()

    def say(self, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(tr("Enter a chat message or server command."))
        if len(text.encode("utf-8")) > 512 or any(unicodedata.category(char) == "Cc" for char in text):
            raise ValueError(tr("Chat messages must be at most 512 bytes and contain no control characters."))
        # Validate and enqueue under the same client lock, so a disconnect does
        # not turn this action into a delayed message on a later connection.
        with self.client._lock:
            if not self.client.connected:
                raise ValueError(tr("Connect to the room before sending a chat message."))
            if len(self.client._outbox) >= 32:
                raise ValueError(tr("The chat queue is full. Wait for the connection to catch up."))
            self.client._outbox.append({"cmd": "Say", "text": text.strip()})
        self.client._wake.set()

    def summary(self):
        return dict(self.client.summary(), tracking=self.status, deathlink=self.deathlink.status)


def supported_platform():
    return live_memory.supported()
