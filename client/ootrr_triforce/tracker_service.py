"""Read-only AP history and observed save inventory for one bound room."""
import json
from pathlib import Path

from .room_library import room_progress


def _inventory_rows(tracker):
    counts, known, tracked = tracker.inventory()
    observations = tracker.inventory_observations()
    return [{"name": name, "count": counts.get(name, 0), "known": name in known,
             "observation": observations.get(name, "Recorded progression")}
            for name in sorted(tracked)]


class ProfileTracker:
    def __init__(self, profile, artifact=None):
        self.profile = Path(profile).resolve()
        self.tracker = None
        self.status = "Inventory tracking is available for prepared full-network rooms."
        if artifact:
            directory = Path(artifact).resolve()
            try:
                raw = (directory / "manifest.json").read_bytes()
                if len(raw) > 4 << 20:
                    raise ValueError()
                manifest = json.loads(raw)
                if (manifest.get("archipelago") or {}).get("token") != self.profile.name:
                    raise ValueError()
                from ootrr_full.tracker.auto_tracker import TrackerSession
                slot = room_progress(self.profile)["slot"] or "Link"
                self.tracker = TrackerSession(directory, slot, manual_directory=self.profile / "tracker")
                self.status = "Choose a save to track inventory and accessibility."
            except (OSError, ValueError, KeyError, ImportError):
                self.status = "The full-network tracker data could not be verified. Prepare this room again."

    def saves(self):
        root = self.profile / "user/save"
        if not root.is_dir():
            return []
        return sorted(str(path) for path in root.glob("*/slot_??/progress.sav")
                      if path.is_file() and not path.is_symlink())

    def refresh(self, save_path=""):
        result = room_progress(self.profile)
        result.update(inventory=[], keys=[], souls=[], tracking_status=self.status, saves=self.saves())
        for row in result["locations"]:
            row["access"] = "unknown"
        if self.tracker is None or not save_path:
            return result
        path = Path(save_path).resolve()
        # A desktop room tracker only observes this room's isolated user tree.
        # External emulators use their own explicitly selected runtime instead.
        if not path.is_relative_to(self.profile / "user"):
            result["tracking_status"] = "Choose a save from this room's profile."
            return result
        self.tracker.save_path = str(path)
        summary = self.tracker.refresh()
        status = summary.get("status", "")
        if status.startswith("Synced with the latest save"):
            result["tracking_status"] = "Inventory and access are read from the selected save."
        elif "not linked to this seed" in status:
            result["tracking_status"] = "This save belongs to another seed. Its inventory is not used."
        else:
            result["tracking_status"] = "The selected save is unavailable. The last valid inventory is kept."
        states = {check["name"]: self.tracker.check_state(check["id"]) for check in self.tracker.checks}
        for row in result["locations"]:
            state = states.get(row["name"], {})
            row["access"] = state.get("access", "unknown")
            row["observed"] = bool(state.get("observed"))
        result["inventory"] = _inventory_rows(self.tracker)
        result["keys"], result["souls"] = self.tracker.keys(), self.tracker.souls()
        return result


class RuntimeTracker:
    """Read the existing external runtime; never construct another AP client."""
    def __init__(self, runtime):
        self.runtime = runtime

    def refresh(self, _save_path=""):
        tracker, client = self.runtime.tracker, self.runtime.client
        with client._lock:
            checked = set(client.reporter.server_checked)
            identities = dict(client.reporter.location_ids)
        rows = []
        for check in tracker.checks:
            ident = identities.get(check["id"])
            if ident is None:
                continue
            state = tracker.check_state(check["id"])
            rows.append({"id": ident, "name": check["name"], "checked": ident in checked or bool(state.get("observed")),
                         "access": state.get("access", "unknown")})
        snapshot = self.runtime.summary()
        return {"slot": client.slot_name, "room": "", "checked": sum(row["checked"] for row in rows), "total": len(rows),
                "won": tracker.goal_reached, "locations": rows, "saves": [], "keys": tracker.keys(), "souls": tracker.souls(),
                "tracking_status": snapshot.get("tracking", ""),
                "inventory": _inventory_rows(tracker)}
