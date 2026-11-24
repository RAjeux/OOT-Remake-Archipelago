"""Console names and spoiler-free views for the current AP room."""
from .i18n import tr, get_language
from .item_names import item_name
from .catalog import GAME, LEGACY_GAME, ITEM_IDS, LOCATION_IDS


def printable(value):
    return "".join(c if c.isprintable() else " " for c in str(value))


class RoomView:
    def __init__(self, slot):
        self.slot = slot
        self.team = 0
        self.players = {0: "Archipelago"}
        self.games = {slot: GAME}
        self.names = {
            GAME: {"item_id": {v: k for k, v in ITEM_IDS.items()},
                   "location_id": {v: k for k, v in LOCATION_IDS.items()}}
        }
        self.names[LEGACY_GAME] = self.names[GAME]
        self.waiting = False
        self.messages = []
        self.on_message = None

    def connected(self, packet):
        self.team = packet.get("team", 0)
        self.games.update({int(k): v["game"] for k, v in packet.get("slot_info", {}).items()})
        self.players.update({int(k): printable(v["name"]) for k, v in packet.get("slot_info", {}).items()})
        self.update_players(packet)
        needed = sorted(set(self.games.values()) - self.names.keys())
        self.waiting = bool(needed)
        self.messages.clear()
        return needed

    def update_players(self, packet):
        for p in packet.get("players", ()):
            team, slot, alias, name = ((p["team"], p["slot"], p["alias"], p["name"])
                                       if isinstance(p, dict) else p[:4])
            if team == self.team:
                self.players[slot] = printable(alias or name)

    def load_package(self, packet):
        for game, fields in packet.get("data", {}).get("games", {}).items():
            self.names[game] = {kind + "_id": {v: k for k, v in fields.get(kind + "_name_to_id", {}).items()}
                                for kind in ("item", "location")}
        self.waiting = bool(set(self.games.values()) - self.names.keys())
        if self.waiting:
            return
        for message in self.messages:
            self.show(message)
        self.messages.clear()

    def name(self, kind, value, player):
        try:
            value = int(value)
            player = int(player)
        except (ValueError, TypeError):
            return printable(value)
        if kind == "player_id":
            return self.players.get(value, tr('Player {value0}', value0=value))
        if kind == "location_id" and value < 0:
            return {-1: "Cheat Console", -2: "Server"}.get(value, tr('Location {value0}', value0=value))
        names = self.names.get(self.games.get(player), {}).get(kind, {})
        return printable(names.get(value, f"#{value}"))

    def display_name(self, kind, value, player):
        canonical = self.name(kind, value, player)
        if kind != "item_id":
            return canonical
        try:
            game = self.games.get(int(player))
        except (ValueError, TypeError):
            return canonical
        return item_name(canonical, get_language(), game=game) if game else canonical

    def show(self, packet):
        if self.waiting:
            self.messages.append(packet)
            return
        if self.on_message:
            self.on_message(packet)
        parts = []
        for part in packet.get("data", ()):
            kind = part.get("type")
            value = part.get("text", "")
            if kind in ("player_id", "location_id", "item_id"):
                value = self.display_name(kind, value, part.get("player", self.slot))
            parts.append(printable(value))
        if parts:
            print("[AP] " + "".join(parts), flush=True)

    def origin(self, player, location):
        return (self.name("player_id", player, self.slot) + " · "
                + self.name("location_id", location, player))
