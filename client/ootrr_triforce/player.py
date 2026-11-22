from .i18n import tr, get_language, set_language, detect_language
from .item_names import item_name
import argparse
from collections import Counter
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from .catalog import CHESTS, SHOP_CHECKS, AP_SKULL_CHECKS, PINNED_SKULL_CHECKS, EXPECTED, FILLER, GAME, LEGACY_GAME, GEAR, ITEM_IDS, LOCATION_IDS, PROTOCOL
from .engine import run_engine
from .settings import yaml_options
from .live import LiveInventory
from .room_view import RoomView
from .presentation import Presentation
from .medallions import prepare
from . import install_mod
from . import native_setup
from .title_screen import write_title
from .save_bridge import Snapshot, apply_history, exclusive, history_cursor, save_path, write_json

BY_ID = {v: k for k, v in ITEM_IDS.items()}


def export_yaml():
    name = input(tr('Your Archipelago player name: ')).strip()
    if not name or name == "Archipelago" or len(name) > 16:
        raise ValueError(tr('Choose a name of 1 to 16 characters other than Archipelago.'))
    folder = choose(tr('Choose the folder in which to save the YAML'), folder=True)
    # Prefix keeps Windows device names (such as CON) usable as slot names.
    basename = "Player-" + re.sub(r"[^\w -]", "_", name)
    filename = folder / (basename + ".yaml")
    index = 1
    content = ("# Supported OOT Remake Archipelago settings for Triforce.\n"
               "# Edit the values below before generating the room.\n"
               f"name: {json.dumps(name, ensure_ascii=False)}\ngame: {json.dumps(GAME)}\n"
               f"{json.dumps(GAME)}:\n" + yaml_options() +
               "\n  # Share deaths with other DeathLink players.\n  death_link: false\n")
    while True:
        try:
            with filename.open("x", encoding="utf-8") as out:
                out.write(content)
            break
        except FileExistsError:
            index += 1
            filename = folder / f"{basename}-{index}.yaml"
    print(tr('Player file created: {value0}', value0=filename), flush=True)


def read_manifest(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("game", LEGACY_GAME) not in (GAME, LEGACY_GAME):
        raise ValueError(tr('This file belongs to another Archipelago game.'))
    seed = data["seed_file"]
    token = hashlib.sha256(f"{data['room']}/{data['player']}/{seed['checksum']}".encode()).hexdigest()
    if (data["protocol"] != PROTOCOL or data["token"] != token
            or seed["generator"] != "ootrr-core 0.8.1" or seed["format"] != "ootrr-seed"):
        raise ValueError(tr('Incompatible player file or version.'))
    allowed=set(CHESTS) | (set(SHOP_CHECKS) if data.get("kokiri_shop_checks") else set())
    skull_mode=data.get("shuffle_skulltulas", "off")
    if skull_mode not in {"off", "pinned", "matched"}:
        raise ValueError(tr('Unknown Gold Skulltula shuffle mode.'))
    if skull_mode!="off":
        local=data.get("local_skulltulas", {})
        if not isinstance(local,dict):
            raise ValueError(tr('Invalid local Skulltula list.'))
        skulls=set(PINNED_SKULL_CHECKS if skull_mode=="pinned" else AP_SKULL_CHECKS)
        # OOTRR explicitly leaves this bean route outside its access proof
        # without planted/starting beans. Its canonical reward stays local.
        if "ZR GS Near Raised Grottos" in local:
            skulls.discard("ZR GS Near Raised Grottos")
        allowed.update(skulls)
    if len(set(data["checks"])) != len(data["checks"]) or not set(data["checks"]) <= allowed:
        raise ValueError(tr('Unknown Archipelago location list.'))
    mode = data.get("reward_mode", "legacy_gear")
    if mode not in ("legacy_gear", "all_chest_rewards", "all_locations"):
        raise ValueError(tr('Unknown Archipelago reward mode.'))
    rewards=dict(seed["placements"])
    if data.get("kokiri_shop_checks"):
        shops=seed.get("shops",{})
        if not all(name in shops for name in SHOP_CHECKS):
            raise ValueError(tr('The seed does not contain all eight Kokiri purchases.'))
        rewards.update({name:shops[name]["item"] for name in SHOP_CHECKS})
    if not set(data["checks"]) <= rewards.keys():
        raise ValueError(tr('An Archipelago location is missing from the OOTRR seed.'))
    if mode in ("all_chest_rewards", "all_locations"):
        if bool(data.get("local_items",False)) != (mode=="all_locations"):
            raise ValueError(tr("Local-item settings do not match this room's mode."))
        expected = {n: rewards[n] for n in data["checks"]}
        if set(data["checks"]) != set(rewards).intersection(allowed):
            raise ValueError(tr('The Archipelago location list is incomplete.'))
        if not set(expected.values()) <= ITEM_IDS.keys():
            raise ValueError(tr('The seed contains an unsupported reward.'))
    else:
        expected = {n: seed["placements"][n] for n in data["checks"] if seed["placements"][n] in GEAR}
    if expected != data["moved"]:
        raise ValueError(tr('The reward list does not match the seed.'))
    return data


def choose(label, suffix=None, folder=False):
    print(label, flush=True)
    if os.name == "nt":
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            return Path(input(tr('Full path: ')).strip().strip(chr(34))).resolve()
        root = tk.Tk()
        root.withdraw()
        try:
            result = (filedialog.askdirectory(title=label) if folder else
                      filedialog.askopenfilename(title=label, filetypes=[(label, suffix or "*"), (tr('All files'), "*")]))
        finally:
            root.destroy()
    else:
        result = input("> ").strip().strip('"')
    if not result:
        raise ValueError(tr('Selection cancelled.'))
    return Path(result).resolve()


def patch_request(data):
    files = {}
    for name, gear in data["moved"].items():
        if name not in CHESTS:
            continue
        for ref in CHESTS[name]:
            request = {"actor": ref["actor"], "drop": "TBox_Rupee_Green", "expected": EXPECTED[gear]}
            for filename in ref["files"]:
                files.setdefault(filename, []).append(request)
    return {"files": files}


def preparation_settings(settings, data):
    """Bind text localization to the player's canonical seed, never UI defaults."""
    result = dict(settings)
    seed = data.get("seed_file", {})
    if "settings" in seed:
        result["_seed_settings"] = seed["settings"]
    else:
        result.pop("_seed_settings", None)
    return result


def build(root, settings, data):
    root.mkdir(parents=True,exist_ok=True)
    dest = root / "mods"
    if dest.is_dir() and (dest / "Archipelago" / "romfs").is_dir():
        return
    if dest.exists():
        raise ValueError(tr('Incomplete mod folder. Move it aside to retry: {value0}', value0=dest))
    with tempfile.TemporaryDirectory(dir=root, prefix="build-") as tmp:
        scratch = Path(tmp)
        native = scratch / "room.ootrr"
        native.write_text(json.dumps(data["seed_file"]), encoding="utf-8")
        stage = scratch / "mods"
        romfs = Path(settings["romfs"])
        if not (romfs / "Pack" / "ZsDic.pack.zs").is_file():
            raise ValueError(tr('Select the romfs folder containing Pack and Model.'))
        for name, original in settings.get("other_tables", {}).items():
            table = stage / name / "romfs" / install_mod.REST
            table.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(original,table)
        subprocess.run([settings["ootrr"], "build", str(native), str(romfs), str(stage),
                        "Archipelago", "--host", settings.get("host","nx2navi"), "--no-title-logo"], check=True)
        mod = stage / "Archipelago" / "romfs"
        print(run_engine("patch", patch_request(data), romfs, mod).strip(), flush=True)
        write_title(romfs, mod)
        if data.get("reward_mode") in ("all_chest_rewards", "all_locations"):
            from .receipt_events import prepare_receipts
            prepare_receipts(romfs,mod,data)
        if settings.get("native"):
            native_setup.bind_romfs(romfs,mod,data,settings["baseline"])
            shutil.copy2(Path(sys.argv[0]).resolve().parent/"native/archipelago.dll",mod.parent/"archipelago.dll")
        # Only the generated mod leaves the build directory. Sibling table inputs are temporary.
        completed = scratch / "completed"
        completed.mkdir()
        (stage/"Archipelago").rename(completed/"Archipelago")
        completed.rename(dest)


def spawn_game(root, settings, live):
    game = Path(settings["exe"])
    env = dict(os.environ, HOS_MODS=str(settings.get("visual_mods", root / "mods")), HOS_SAVE_LOCK="1")
    native_for_setup = {"triforcesetup.exe": "Triforce.exe", "hookshotsetup.exe": "hookshot.exe"}
    if os.name == "nt" and game.name.lower() in native_for_setup:
        # Use only the selected launcher's own native build when it is available.
        native_dir = Path(settings["romfs"]).parent
        native_name = native_for_setup[game.name.lower()]
        for directory in (game.parent, native_dir):
            native = directory / native_name
            if native.is_file() and (directory / "image.bin").is_file():
                game = native
                break
    image = next((d / "image.bin" for d in (game.parent, Path(settings["romfs"]).parent)
                  if (d / "image.bin").is_file()), None)
    args = [str(game), *([str(image)] if image else []), "--romfs", settings["romfs"], "--user", str(root / "user")]
    if os.name != "nt" or game.name.lower() not in ("triforce.exe", "hookshot.exe") or image is None:
        live.enabled = False
        print(tr('Save-based delivery. Live delivery requires a Windows port supporting inventory commands.'), flush=True)
        return subprocess.Popen(args, cwd=game.parent, env=env)
    live.input.write_bytes(b"")
    env["HOS_INPUT_LIVE"] = str(live.input)
    with live.log.open("wb") as log:
        return subprocess.Popen(args, cwd=game.parent, env=env, stderr=log)


class Session:
    def __init__(self, root, slot, data):
        self.root, self.slot, self.data = root, slot, data
        self.slots_dir, self.ledger = None, root
        self.manual_sync = False
        self.checked = set()
        self.reported = set()
        self.history = []
        self.origins = []
        self.room = RoomView(data["player"])
        self.visual = Presentation(root, data, self.room)
        self.room.on_message = self.visual.outgoing
        self.auth = self.synced = self.sent_goal = False
        self.manual_goal = False
        self.process = None
        self.stamp = None
        self.resolved_slot = None
        self.local_goal = False
        self.opend = set()
        self.pending_launch = False
        self.want_exit = False
        self.cache = None
        self.live = None
        self.saved_gear = set()
        self.ambiguous_slot = False

    def configure_save(self, config):
        self.slots_dir = Path(config["slots_dir"]) if config.get("slots_dir") else None
        self.ledger = self.root
        if self.slots_dir and self.slots_dir.parent != self.root / "user" / "save":
            tag = hashlib.sha256(os.fsencode(os.path.normcase(str(self.slots_dir)))).hexdigest()[:16]
            self.ledger = self.root / ("profil-" + tag)
            self.ledger.mkdir(exist_ok=True)

    def connected(self, msg):
        slot_data = msg.get("slot_data") or {}
        if (slot_data.get("protocol") != PROTOCOL or slot_data.get("token") != self.data["token"]
                or msg.get("slot") != self.data["player"] or
                set(slot_data.get("checks", [])) != {LOCATION_IDS[n] for n in self.data["checks"]}):
            raise ValueError(tr('The player file and server slot belong to different generations.'))
        self.checked = set(msg["checked_locations"])
        self.reported = set(self.checked)
        self.auth = True
        self.visual.join(msg)

    def receive(self, index, entries):
        ids = [entry["item"] if isinstance(entry, dict) else entry[0] for entry in entries]
        origins = [(entry["player"], entry["location"]) if isinstance(entry, dict) else (entry[2], entry[1])
                   for entry in entries]
        if any(v not in BY_ID for v in ids):
            raise ValueError(tr('Unknown received item. Check the APWorld version.'))
        if index < 0 or index > len(self.history) or (not self.synced and index != 0):
            return False
        end = index + len(ids)
        overlap = min(len(ids), len(self.history) - index)
        if self.history[index:index + overlap] != ids[:overlap] or self.origins[index:index + overlap] != origins[:overlap]:
            return False
        old = len(self.history)
        if end > old:
            self.history.extend(ids[max(0, old-index):])
            self.origins.extend(origins[max(0, old-index):])
            counts = Counter(BY_ID[v] for v in self.history[old:])
            print(tr('Received for your world: ') + ", ".join(
                f"{item_name(n, get_language())} ×{count}" if count > 1 else item_name(n, get_language())
                for n,count in counts.items()), flush=True)
            if FILLER in counts:
                print(tr('Blue rupees will be credited when the save is synchronized.'), flush=True)
        self.synced = True
        return True

    def show_items(self, query):
        if not self.synced:
            print(tr('Item history is being synchronized.'), flush=True)
            return
        cursor = history_cursor(self.ledger)
        found = False
        for i, (code, (player, location)) in enumerate(zip(self.history, self.origins)):
            name = BY_ID[code]
            display = item_name(name, get_language())
            origin = self.room.origin(player, location)
            if query.casefold() not in (name + " " + display + " " + origin).casefold():
                continue
            if name == FILLER:
                state = tr('applied to save') if i < cursor else tr('to credit after closing')
            elif name in self.saved_gear:
                state = tr('present in save')
            elif self.live and name in self.live.finished:
                state = tr('confirmed in game')
            elif self.live and name in self.live.deferred:
                state = tr('delivery deferred')
            else:
                state = tr('pending')
            print(f"{display} | {origin} | {state}", flush=True)
            found = True
        if not found:
            print(tr('No matching received item.'), flush=True)

    def show_chests(self, query):
        checks = self.data["checks"]
        count = sum(LOCATION_IDS[name] in self.checked for name in checks)
        print(tr('{value0}/{value1} chests checked by the server.', value0=count, value1=len(checks)), flush=True)
        if self.slot == "auto" and self.stamp is None:
            print(tr('Waiting for an identifiable save. Save in Zelda to update its internal timestamp.'), flush=True)
        if query:
            matches = [name for name in checks if query.casefold() in name.casefold()]
            for name in matches:
                status = tr('checked') if LOCATION_IDS[name] in self.checked else tr('unchecked')
                print(f"{name} | {status}", flush=True)
            if not matches:
                print(tr('No matching chest.'), flush=True)

    def observe(self):
        p = save_path(self.root / "user", self.slot, self.slots_dir)
        if not p:
            self.stamp = None
            self.opend = set()
            self.local_goal = False
            self.saved_gear.clear()
            return
        st = p.stat()
        stamp = (p, st.st_mtime_ns, st.st_size, st.st_ino)
        if stamp == self.stamp:
            return
        snap = Snapshot(p.read_bytes())
        if self.resolved_slot != p.parent.name:
            self.resolved_slot = p.parent.name
            if self.slot == "auto":
                print(tr('Tracked save: ') + self.resolved_slot, flush=True)
            if self.live:
                self.live.finished.clear()
        self.opend = snap.checks(self.data["checks"])
        self.local_goal = snap.won()
        previous = self.saved_gear
        self.saved_gear = {name for name, flags in GEAR.items()
                           if all(flag in snap.offsets and snap.get(flag) > 0 for flag in flags)}
        if self.live:
            self.live.finished.difference_update(previous - self.saved_gear)
        self.stamp = stamp

    async def ready_mod(self, config):
        if self.visual.mods is not None:
            return True
        roster = self.visual.roster()
        if roster is None:
            return False
        if self.visual.build_task is None:
            def publish():
                assets = config.get("assets", self.root)
                try:
                    source = prepare(assets, preparation_settings(config, self.data), roster, self.data["moved"])
                except Exception as exc:
                    import traceback
                    diagnostic=self.root/"medaillons-diagnostic.txt"
                    diagnostic.write_text(traceback.format_exc(),encoding="utf-8")
                    if self.data.get("reward_mode") in ("all_chest_rewards", "all_locations"):
                        raise ValueError(tr('Archipelago preparation failed; the installed mod is preserved. Details: {value0}', value0=diagnostic)) from exc
                    print(tr('3D medals unavailable ({value0}). Details: {value1}', value0=exc, value1=diagnostic),flush=True)
                    source = assets / "mods"
                if config.get("mods_dir"):
                    if config.get("native"):
                        native_setup.save_session(self.root,config,self.data,roster,prepared=source/"Archipelago"/"romfs")
                    dest = install_mod.install(source, Path(config["mods_dir"]), self.data["token"])
                    print(tr('Mod installed: {value0}', value0=dest),flush=True)
                    return dest.parent
                return source
            self.visual.build_task = asyncio.create_task(asyncio.to_thread(publish))
        if not self.visual.build_task.done():
            return False
        try:
            self.visual.mods = self.visual.build_task.result()
        except OSError as exc:
            raise ValueError(tr('Unable to install the mod: {value0}', value0=exc)) from exc
        return True

    async def tick(self, send, config):
        if self.visual.active and (self.pending_launch or config.get("install_only") or self.slots_dir):
            if not self.auth or not self.synced or not await self.ready_mod(config):
                return
        if config.get("install_only"):
            self.want_exit = True
            return
        try:
            self.observe()
        except (FileNotFoundError, PermissionError):
            return
        except ValueError as exc:
            if not self.slots_dir:
                raise
            if str(exc) != getattr(self, "last_save_error", None):
                print(tr("Unable to read the port's save: {value0}", value0=exc), flush=True)
                self.last_save_error = str(exc)
            self.manual_sync = False
            return
        if self.auth:
            new = self.opend - self.reported
            if new:
                await send({"cmd":"LocationChecks", "locations": sorted(new)})
                self.reported.update(new)
                print(tr('Chests sent: ') + ", ".join(n for n in self.data["checks"] if LOCATION_IDS[n] in new), flush=True)
            if (self.local_goal or self.manual_goal) and not self.sent_goal:
                await send({"cmd":"StatusUpdate", "status":30})
                self.sent_goal = True
                print(tr('Victory sent to Archipelago.'), flush=True)
        running = self.process is not None and self.process.poll() is None
        if not self.auth or not self.synced:
            return
        if self.visual.active:
            self.visual.receipts(self.history, self.origins)
        if self.slots_dir is not None:
            if self.pending_launch:
                self.pending_launch = False
                print(tr('Open the game in your launcher. Chests are read on each save. To receive items, close the game and enter sync closed.'),flush=True)
            if self.manual_sync:
                self.manual_sync = False
                try:
                    applied = apply_history(self.ledger, self.slot, self.history, self.slots_dir)
                except (PermissionError, BlockingIOError):
                    applied = False
                print(tr('Inventory synchronized. You can restart the game.') if applied else
                      tr('No save is available for this synchronization.'),flush=True)
            return
        if running:
            if self.live and self.live.enabled and self.stamp:
                wanted = [BY_ID[code] for code in self.history if BY_ID[code] in GEAR
                          and (self.slot == "auto" or BY_ID[code] not in self.saved_gear)]
                if wanted or self.live.item:
                    others = self.slot != "auto" and any(p.parent.name != self.slot for p in (self.root / "user" / "save").glob("*/slot_*/progress.sav"))
                    if not others:
                        self.live.tick(wanted)
                    elif not self.ambiguous_slot:
                        self.ambiguous_slot = True
                        print(tr('Multiple Zelda files in this profile. Items will be delivered after closing to respect the selected file.'), flush=True)
            return
        if self.process is not None:
            self.process = None
            self.visual.hud.close()
            print(tr('The game is closed. Enter play to resume.'), flush=True)
        marker = (self.stamp, len(self.history))
        needs_delivery = self.history and self.cache != marker
        if needs_delivery:
            try:
                applied = apply_history(self.root, self.slot, self.history)
            except (BlockingIOError, PermissionError):
                return
            if applied:
                self.observe()
                self.cache = (self.stamp, len(self.history))
                print(tr('Inventory synchronized.'), flush=True)
            elif save_path(self.root / "user", self.slot):
                if self.pending_launch:
                    print(tr('The game must finish a pending save on its next start.'), flush=True)
        if self.pending_launch:
            try:
                with exclusive(self.root / "user" / "save.lock"):
                    pass
            except BlockingIOError:
                self.pending_launch = False
                print(tr("This room's game is already running."), flush=True)
                return
            self.pending_launch = False
            self.live = LiveInventory(self.root)
            launch_config = dict(config, visual_mods=self.visual.mods) if self.visual.mods else config
            self.process = spawn_game(self.root, launch_config, self.live)
            if self.visual.active:
                self.visual.hud.start(self.process.pid)
            if self.slot == "auto":
                print(tr("Game started. Continue your most recent file. Tracking uses Zelda's recorded timestamp."), flush=True)
            else:
                print(tr('Game started. Create or load the game file for {value0}.', value0=self.slot), flush=True)
            print(tr('Equipment and songs are received live on compatible versions. Save once in a new game.'), flush=True)


async def play(root, slot, data, config, uri, password, headless=False):
    from websockets.legacy.client import connect
    from websockets.exceptions import ConnectionClosed
    set_language(detect_language(root, config))
    s = Session(root, slot, data)
    s.configure_save(config)
    if config.get("install_only") or s.slots_dir:
        s.visual.active = True
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    if not headless:
        s.visual.active = True
        import threading
        def read_commands():
            try:
                for line in sys.stdin:
                    loop.call_soon_threadsafe(queue.put_nowait, line.strip())
            except (OSError, RuntimeError):
                pass
        threading.Thread(target=read_commands, daemon=True).start()
        print(tr('Enter help for commands. Examples: items, chests Mido, !hint or say Hello.'), flush=True)
        s.pending_launch = True
    while not s.want_exit:
        try:
            async with connect(uri, max_size=32*1024*1024, open_timeout=15) as ws:
                s.auth = s.synced = s.sent_goal = False
                s.history = []
                s.origins = []
                s.cache = None
                fence = "ootrr-ap-sync-" + uuid.uuid4().hex
                async def send(*packets):
                    await ws.send(json.dumps(packets))
                while not s.want_exit:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    except asyncio.TimeoutError:
                        raw = None
                    for m in json.loads(raw) if raw else []:
                        cmd = m["cmd"]
                        if cmd == "RoomInfo":
                            if m.get("seed_name") != data["room"]:
                                raise ValueError(tr('Wrong Archipelago room for this player file.'))
                            await send({"cmd":"Connect", "name":data["slot"], "game":data.get("game", LEGACY_GAME), "uuid":str(uuid.uuid4()),
                                        "password":password or None, "items_handling":5 if data.get("local_items") else 7,
                                        "tags":["AP"], "slot_data":True,
                                        "version":{"major":0,"minor":6,"build":7,"class":"Version"}})
                        elif cmd == "ConnectionRefused":
                            raise ValueError(tr('Connection refused: ') + ", ".join(m["errors"]))
                        elif cmd == "Connected":
                            s.connected(m)
                            needed = s.room.connected(m)
                            if s.visual.active and s.visual.checks:
                                await send({"cmd": "LocationScouts", "locations": sorted(s.visual.checks), "create_as_hint": 0})
                            if needed:
                                await send({"cmd": "GetDataPackage", "games": needed})
                            print(tr('Connected to slot {value0} ({value1} chests).', value0=data['slot'], value1=len(data['checks'])), flush=True)
                            # Core sends no ReceivedItems for an empty queue. Get is an ordered fence.
                            await send({"cmd":"Sync"}, {"cmd":"Get", "keys":[fence]})
                        elif cmd == "ReceivedItems" and s.auth:
                            if not s.receive(m["index"], m["items"]):
                                s.synced = False
                                s.history = []
                                s.origins = []
                                await send({"cmd":"Sync"}, {"cmd":"Get", "keys":[fence]})
                        elif cmd == "Retrieved" and s.auth and fence in m.get("keys", {}):
                            s.synced = True
                            s.visual.fenced = True
                        elif cmd == "LocationInfo" and s.auth:
                            s.visual.scout(m["locations"])
                        elif cmd == "RoomUpdate":
                            s.checked.update(m.get("checked_locations", []))
                            s.room.update_players(m)
                        elif cmd == "DataPackage":
                            s.room.load_package(m)
                        elif cmd == "PrintJSON":
                            s.room.show(m)
                        elif cmd == "InvalidPacket":
                            s.room.show({"data": [{"text": m.get("text", tr('The server refused the request.'))}]})
                    while not queue.empty():
                        line = queue.get_nowait()
                        action, _, query = line.partition(" ")
                        query = query.strip()
                        if line.casefold() in {"quit", "quitter"}:
                            s.want_exit = True
                        elif line.casefold() in {"play", "jouer"}:
                            s.pending_launch = s.process is None or s.process.poll() is not None
                        elif line.casefold() in {"sync closed", "sync ferme"} and s.slots_dir:
                            s.manual_sync = True
                        elif line.casefold() == "notif" and s.slots_dir:
                            print(tr('Notifications for this port are shown in this console.'),flush=True)
                        elif line.casefold() == "notif":
                            s.visual.hud.notify(tr('Notification test'), tr('Archipelago medal'),
                                                tr('Return to the Zelda window to see this message.'), "out")
                            print(tr('Test notification prepared for Zelda.'), flush=True)
                        elif line.casefold() == "ganon":
                            print(tr('After defeating Ganon, enter confirm ganon.'), flush=True)
                        elif line.casefold() in {"confirm ganon", "confirmer ganon"}:
                            s.manual_goal = True
                        elif action.casefold() in {"items", "objets"}:
                            s.show_items(query)
                        elif action.casefold() in {"chests", "coffres"} and s.auth:
                            s.show_chests(query)
                        elif action.startswith("!") or (action.casefold() in {"say", "dire"} and query):
                            if s.auth:
                                await send({"cmd": "Say", "text": line if action.startswith("!") else query})
                            else:
                                print(tr('Wait for the server connection, then retry.'), flush=True)
                        elif line:
                            print(tr('Local commands: play, quit, items [filter], chests [filter], notif, sync closed, ganon. Room commands: say <message>, !help, !hint.'), flush=True)
                    await s.tick(send, config)
        except (ConnectionClosed, OSError, asyncio.TimeoutError) as exc:
            print(tr('Connection interrupted ({value0}). Retrying in five seconds. Ctrl+C to exit.', value0=exc), flush=True)
            await asyncio.sleep(5)


def launch_setup(mods):
    setup = choose(tr("Choose your port's build executable"), "*.exe")
    subprocess.run([str(setup)],cwd=setup.parent,env=dict(os.environ,HOS_MODS=str(mods)),check=True)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--hud":
        from .hud import overlay
        overlay(int(sys.argv[2]))
        return
    p = argparse.ArgumentParser(description="Archipelago — Ocarina of Time Remake / OOTRR 0.8.1.")
    p.add_argument("manifest", nargs="?")
    p.add_argument("--server")
    p.add_argument("--ootrr")
    p.add_argument("--game")
    p.add_argument("--romfs")
    p.add_argument("--save-slot", default="auto", help=tr("Track the room's latest save, or select a slot_NN."))
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--export-yaml", action="store_true", help=tr('Create a player YAML for a new room.'))
    p.add_argument("--setup", action="store_true", help=tr("Open the port's build tool with this room's mod folder."))
    p.add_argument("--mods", help=tr('Mod folder used by OOTRR.'))
    p.add_argument("--choose-mods", action="store_true")
    p.add_argument("--choose-port", action="store_true")
    p.add_argument("--host", choices=install_mod.HOSTS)
    p.add_argument("--install-only", action="store_true", help=tr("Install the room's complete mod without starting the game."))
    p.add_argument("--native-install", action="store_true", help=tr('Prepare the mod with the in-game Archipelago connection.'))
    p.add_argument("--external", action="store_true", help=tr('Start the game yourself and track its save.'))
    p.add_argument("--saves", help=tr('External port folder containing slot_00, slot_01 and so on.'))
    args = p.parse_args()
    if args.native_install:
        args.install_only=True
        if os.name!="nt":
            p.error(tr('Configure the native port on the Windows game PC.'))
    if args.export_yaml:
        export_yaml()
        return
    if args.save_slot != "auto" and not re.fullmatch(r"slot_[0-9]{2}", args.save_slot):
        p.error(tr('--save-slot accepts auto or a name such as slot_04'))
    manifest = args.manifest or choose(tr('Choose your Archipelago player file'), "*.apootrr")
    data = read_manifest(manifest)
    if data.get("reward_mode") in ("all_chest_rewards", "all_locations") and not (args.native_install or args.build_only):
        raise ValueError(tr('This room uses all chest rewards. Configure its native mod, then start Triforce.'))
    base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / ".local/share")) / "OOTRR-Archipelago"
    root = base / data["token"]
    (root / "user").mkdir(parents=True, exist_ok=True)
    config_path = base / "outils.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    set_language(detect_language(root, cfg))
    host = args.host or ("nx2navi" if args.native_install else cfg.get("host", "nx2navi"))
    if args.choose_port:
        print(tr('1. Triforce or NX2Navi   2. Hookshot   3. Longshot'))
        choices = {"1":"nx2navi","2":"hookshot","3":"longshot"}
        while True:
            selected = input(tr('Port number: ')).strip()
            if selected in choices:
                host = choices[selected]
                break
            print(tr('Enter 1, 2 or 3.'))
    cfg["host"] = host
    if args.native_install and host != "nx2navi":
        raise ValueError(tr('This native integration requires Triforce Windows tools. Use its mod setup.'))
    profiles = cfg.setdefault("ports",{})
    profile = profiles.setdefault(host,{})
    mods = args.mods or profile.get("mods")
    if args.choose_mods or (args.choose_port and not args.mods):
        mods = choose(tr('Choose the same folder as Mod folder in OOTRR'), folder=True)
    if not mods and host == "nx2navi" and not args.native_install:
        mods = install_mod.known_folder(base.parent)
    if not mods:
        mods = choose(tr('Choose the same folder as Mod folder in OOTRR'), folder=True)
    for key, value, label, folder in (
            ("ootrr", args.ootrr, tr('Choose ootrr.exe from portable version 0.8.1'), False),
            ("romfs", args.romfs, tr("Choose the game's romfs folder, version 1.1.1"), True)):
        old = value or cfg.get(key)
        target = Path(old).resolve() if old else None
        if not target or not (target.is_dir() if folder else target.is_file()):
            target = choose(label, "*.exe", folder)
        cfg[key] = str(target)
    mods = install_mod.validate_root(Path(mods),Path(cfg["romfs"]),base)
    profile["mods"] = str(mods)
    external = args.external or args.saves or host == "longshot"
    if not (args.install_only or args.build_only or args.setup or external):
        exe = args.game or profile.get("exe") or (cfg.get("exe") if host == "nx2navi" else None)
        if not exe or not Path(exe).is_file():
            exe = choose(tr("Choose your port's executable or launcher"), "*.exe")
        profile["exe"] = str(Path(exe).resolve())
        external = Path(exe).name.lower() not in ("triforce.exe","hookshot.exe","triforcesetup.exe","hookshotsetup.exe")
    write_json(config_path,cfg)
    runtime = dict(cfg, mods_dir=str(mods), exe=profile.get("exe"), install_only=bool(args.install_only or args.setup),
                   reward_mode=data.get("reward_mode","legacy_gear"),local_items=bool(data.get("local_items",False)),
                   player=data["player"],kokiri_shop_checks=bool(data.get("kokiri_shop_checks",False)),
                   foreign_only_shops=bool(data.get("foreign_only_shops",False)),
                   shuffle_skulltulas=data.get("shuffle_skulltulas", "off"),
                   shop_prices={name:row["price"] for name,row in data["seed_file"].get("shops",{}).items()
                                if name in SHOP_CHECKS})
    if args.native_install:
        existing=root/"native-session.json"
        previous=json.loads(existing.read_bytes()) if existing.is_file() else {}
        runtime.update(native=True,baseline=previous.get("Baseline", history_cursor(root)))
    if external and not (runtime["install_only"] or args.build_only):
        selection = root / ("sauvegarde-" + host + ".json")
        slots = args.saves or (json.loads(selection.read_text()) if selection.exists() else None)
        if not slots or not Path(slots).is_dir():
            slots = choose(tr("Choose this game's folder containing slot_00, slot_01 and so on"), folder=True)
        slots = Path(slots).resolve()
        if not any(slots.glob("slot_[0-9][0-9]/progress.sav")):
            raise ValueError(tr("Choose the folder containing Zelda's slot_XX files. For a new game, install the mod, start the game and save first."))
        write_json(selection,str(slots))
        runtime["slots_dir"] = str(slots)
    lockdir = install_mod.state_dir(mods)
    lockdir.mkdir(exist_ok=True)
    with exclusive(root / "client.lock"), exclusive(lockdir/"session.lock"):
        install_mod.offer_old_seed(mods)
        inputs = install_mod.tables(mods) if host in ("hookshot","longshot") else {}
        assets = install_mod.build_cache(base,data["token"],host,inputs,Path(cfg["romfs"]))
        if args.native_install:
            assets=assets/native_setup.runtime_cache_name(runtime["baseline"])
        runtime.update(assets=assets,other_tables=inputs)
        build(assets,runtime,data)
        if args.build_only:
            source=prepare(assets,preparation_settings(runtime,data),{},data["moved"])
            install_mod.install(source,mods,data["token"])
            print(tr('Base mod available in'),mods/"Archipelago",flush=True)
            return
        if args.setup and install_mod.marker(mods/"Archipelago").get("room")==data["token"]:
            launch_setup(mods)
            return
        default=previous.get("Server","127.0.0.1:38281") if args.native_install else ""
        uri = args.server or input(tr('Server address{value0} : ', value0=' [' + default + ']' if default else '')).strip() or default
        from .connection_control import ControlError, normalize_server
        try:
            uri = normalize_server(uri)
        except ControlError:
            raise ValueError(tr('Invalid WebSocket address.')) from None
        password = getpass.getpass(tr('Room password (Enter if none): '))
        if args.native_install:
            runtime.update(server=uri,protected=native_setup.protect_password(password))
            cfg["native_tools"]=str(native_setup.install_tools(base,choose,cfg.get("native_tools")))
            write_json(config_path,cfg)
        asyncio.run(play(root, args.save_slot, data, runtime, uri, password))
        if args.native_install:
            write_json(base/"derniere-salle-native.json",data["token"])
            print(tr('Setup complete. The preparation client is disconnecting.'),flush=True)
            if not native_setup.compiled_game(Path(cfg["romfs"]),cfg.get("native_tools")):
                print(tr('Rebuild the game once in Triforce Setup with these tools, then click Launch.'),flush=True)
            else:
                print(tr('The game already contains the Archipelago module. You can click Launch.'),flush=True)
        if args.setup:
            launch_setup(mods)


def cli():
    try:
        main()
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(tr('Error:'), exc, file=sys.stderr)
        sys.exit(1)
