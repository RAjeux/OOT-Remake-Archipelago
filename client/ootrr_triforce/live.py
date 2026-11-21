"""Deliver unique equipment and songs through Triforce’s inventory commands."""
from .i18n import tr, get_language
from .item_names import item_name
import re
import time

# Pouch names from OOTRR 0.8.1 (IsGet) and Triforce’s inventory list.
POUCH = {'Bolero of Fire': 'Item_Melody_FireBolero',
 'Boomerang': 'Item_Boomerang',
 'Dins Fire': 'Item_DinFire',
 'Eponas Song': 'Item_Melody_EponaSong',
 'Farores Wind': 'Item_FaroreWind',
 'Fire Arrows': 'Item_Arrow_Fire',
 'Gerudo Membership Card': 'Item_Token_Gerudo',
 'Goron Tunic': 'Armor_Adult_Goron',
 'Hover Boots': 'Armor_Adult_HoverBoot',
 'Ice Arrows': 'Item_Arrow_Ice',
 'Iron Boots': 'Armor_Adult_HeavyBoot',
 'Lens of Truth': 'Armor_GlassTruth',
 'Light Arrows': 'Item_Arrow_Light',
 'Megaton Hammer': 'Item_Hammer',
 'Minuet of Forest': 'Item_Melody_ForestMinuet',
 'Mirror Shield': 'Weapon_Shield_Mirror',
 'Nayrus Love': 'Item_NayruLove',
 'Nocturne of Shadow': 'Item_Melody_ShadowNocturne',
 'Prelude of Light': 'Item_Melody_LightPrelude',
 'Requiem of Spirit': 'Item_Melody_SpiritRequiem',
 'Sarias Song': 'Item_Melody_SariaSong',
 'Serenade of Water': 'Item_Melody_WaterSerenade',
 'Song of Storms': 'Item_Melody_StormSong',
 'Song of Time': 'Item_Melody_TimeSong',
 'Stone of Agony': 'Item_AgonyStone',
 'Suns Song': 'Item_Melody_SunSong',
 'Zeldas Lullaby': 'Item_Melody_ZeldaLullaby',
 'Zora Tunic': 'Armor_Adult_Zora'}

INVENTORY = "cheats: crawl: items (pouch/GameData):"
ENTRY = re.compile(r"\b(\w+)=(-?\d+)/(-?\d+)(?=\s|$)")
GIVEN = re.compile(r"cheats: crawl: give (\w+) \+1: GameData had (-?\d+) .*?: (set|not set)$")


class LiveInventory:
    def __init__(self, root):
        self.input = root / "commandes-triforce.txt"
        self.log = root / "triforce-session.log"
        self.enabled = True
        self.finished = set()
        self.deferred = {}
        self.item = None
        self.phase = None
        self.have_player = False
        self.offset = 0
        self.partial = b""
        self.started = 0
        self.retry_at = 0
        self.retry_phase = "inspect"

    def command(self, line):
        # The native reader consumes only complete, newline-terminated commands.
        with self.input.open("ab") as stream:
            stream.write((line + "\n").encode("ascii"))

    def probe(self):
        self.have_player = False
        self.command("!items")

    def finish(self, success):
        if success:
            print(tr('Received in game: {value0}', value0=item_name(self.item,get_language())), flush=True)
            self.finished.add(self.item)
            self.deferred.pop(self.item, None)
        else:
            if self.item not in self.deferred:
                print(tr('Delivery deferred for {value0}. Other items can pass it. Retrying in one minute.',
                         value0=item_name(self.item,get_language())), flush=True)
            self.deferred[self.item] = time.monotonic() + 60
        self.item = None
        self.phase = None

    def read_line(self, line):
        if self.phase == "grant":
            ack = GIVEN.search(line)
            if ack and ack[1] == POUCH[self.item]:
                if ack[3] == "set":
                    self.phase = "verify"
                    self.probe()
                else:
                    self.finish(False)
            return
        if self.phase not in ("inspect", "verify") or INVENTORY not in line:
            return
        for actor, pouch, stock in ENTRY.findall(line.split(INVENTORY, 1)[1]):
            if actor == "Weapon_Sword_Kokiri":
                self.have_player = int(pouch) >= 0
            if actor != POUCH[self.item]:
                continue
            if not self.have_player:
                self.retry_phase = self.phase
                self.phase = "waiting"
                self.retry_at = time.monotonic() + 5
            elif int(stock) < 0:
                self.finish(False)
            elif int(stock) > 0:
                self.finish(True)
            elif self.phase == "inspect":
                self.phase = "grant"
                self.started = time.monotonic()
                self.command(f"!give {actor} 1")
            else:
                self.finish(False)
            break

    def tick(self, wanted):
        now = time.monotonic()
        if self.item and now - self.started >= 30:
            # Read the inventory again on retry. An unacknowledged grant may have succeeded.
            self.finish(False)
        if self.phase == "waiting":
            if now < self.retry_at:
                return
            self.phase = self.retry_phase
            self.probe()
        if self.item is None:
            pending = [name for name in wanted if name in POUCH and name not in self.finished]
            self.item = next((name for name in pending if name not in self.deferred), None)
            if self.item is None:
                self.item = next((name for name in pending if now >= self.deferred[name]), None)
            if self.item is None:
                return
            self.offset = self.log.stat().st_size
            self.partial = b""
            self.phase = "inspect"
            self.started = time.monotonic()
            self.probe()
        with self.log.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(512 * 1024)
            self.offset = stream.tell()
        if data:
            *lines, self.partial = (self.partial + data).split(b"\n")
            for line in lines:
                if self.item is None:
                    break
                self.read_line(line.decode("ascii", "replace").rstrip("\r"))
