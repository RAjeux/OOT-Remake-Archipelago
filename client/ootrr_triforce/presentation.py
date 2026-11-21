"""Room-scoped visible AP events. Scouts never announce an unopened chest."""
import json
from .catalog import ITEM_IDS, FILLER, LOCATION_IDS
from .hud import Hud
from .save_bridge import write_json

ITEMS = {v:k for k,v in ITEM_IDS.items()}


class Presentation:
    def __init__(self, root, data, room):
        self.path = root / "notifications-014.json"
        self.cursor = json.loads(self.path.read_text()) if self.path.exists() else None
        self.room = room
        self.full_chests = data.get("reward_mode") == "all_chest_rewards"
        self.local_items = bool(data.get("local_items",False))
        self.checks = {LOCATION_IDS[n]: n for n in data["checks"]}
        self.scouts = {}
        self.hud = Hud()
        self.sent = set()
        self.stable_names = {}
        self.mods = None
        self.build_task = None
        self.active = False
        self.fenced = False

    def join(self, packet):
        self.fenced = False
        self.scouts.clear()
        self.stable_names = {int(k): v["name"] for k,v in packet["slot_info"].items()}
        self.sent.update(packet["checked_locations"])

    def scout(self, records):
        for entry in records:
            item, location, owner = ((entry["item"],entry["location"],entry["player"])
                                     if isinstance(entry, dict) else entry[:3])
            if location in self.checks:
                self.scouts[location] = (item,owner)

    def roster(self):
        if self.room.waiting or self.scouts.keys() != self.checks.keys():
            return None
        result = {}
        for loc,(item,owner) in self.scouts.items():
            if owner == self.room.slot and not (self.full_chests or self.local_items):
                continue
            names = self.room.names.get(self.room.games.get(owner), {}).get("item_id", {})
            if item not in names or owner not in self.stable_names:
                raise ValueError("Le serveur n’a pas fourni le nom d’un objet ou de son destinataire.")
            name,player=self.room.name("item_id",item,owner),self.stable_names[owner]
            result[self.checks[loc]] = ({"item":name,"player":player,"owner":owner,"item_id":item,
                                        "local":owner==self.room.slot} if self.local_items else (name,player))
        return result

    def receipts(self, history, origins):
        if not self.fenced or self.room.waiting:
            return
        if self.cursor is None:
            # First start after upgrading: the old 0.1.3 log can contain hundreds of items.
            self.cursor = len(history)
            write_json(self.path,self.cursor)
            return
        if len(history) <= self.cursor:
            return
        for i in range(self.cursor,len(history)):
            name = ITEMS[history[i]]
            sender = self.room.name("player_id",origins[i][0],self.room.slot)
            detail = "De " + sender
            if name == FILLER:
                detail += " · Rubis crédités à la synchronisation de la sauvegarde"
            self.hud.notify("Objet reçu via Archipelago",name,detail,"in")
        self.cursor = len(history)
        write_json(self.path,self.cursor)

    def outgoing(self, packet):
        if packet.get("type") != "ItemSend":
            return
        row, owner = packet["item"],packet["receiving"]
        item, loc, finder = (row["item"],row["location"],row["player"]) if isinstance(row,dict) else row[:3]
        if finder != self.room.slot or owner == finder or loc in self.sent or loc not in self.checks:
            return
        self.sent.add(loc)
        self.hud.notify("Objet envoyé à " + self.room.name("player_id",owner,finder),
                        self.room.name("item_id",item,owner),self.checks[loc],"out")
