"""Plans use real pool items, obey rules and reject progression deadlocks."""
from collections import Counter
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from ootrr_triforce.catalog import GAME
from ootrr_triforce.item_plando import apply_item_plando

LEFT = "KF Midos Top Left Chest"
RIGHT = "KF Midos Top Right Chest"
BOW = "Bow"
HOOK = "Progressive Hookshot"


class State:
    def __init__(self, items=()):
        self.items = Counter(items)

    def copy(self):
        return State(self.items.elements())

    def collect(self, item, event=False, location=None):
        self.items[item.name, item.player] += 1


def sweep(state, items):
    for item in items:
        state.collect(item)
    return state


class Location:
    def __init__(self, name, needs=()):
        self.name, self.needs = name, tuple(needs)
        self.address, self.item, self.locked = 1, None, False
        self.item_rule = lambda _item: True

    def can_reach(self, state):
        return all(state.items[name, 1] for name in self.needs)

    def place_locked_item(self, item):
        self.item, self.locked, item.location = item, True, self


def room(mapping, items, needs=None):
    locations = {name: Location(name, (needs or {}).get(name, ())) for name in (LEFT, RIGHT)}
    pool = [SimpleNamespace(name=name, player=1, advancement=True, location=None) for name in items]
    world = SimpleNamespace(game=GAME, native_options={"item_plando": mapping}, moved=set(locations))
    return SimpleNamespace(worlds={1: world}, itempool=pool, state=State(),
                           get_location=lambda name, player: locations[name]), locations


class ItemPlandoTests(unittest.TestCase):
    def test_real_items_are_reserved_once_and_original_state_is_untouched(self):
        world, locations = room({LEFT: HOOK}, [HOOK, BOW])
        original = tuple(world.itempool)
        placed = apply_item_plando(world, sweep)
        self.assertIs(placed[0], original[0])
        self.assertIs(locations[LEFT].item, original[0])
        self.assertTrue(locations[LEFT].locked)
        self.assertEqual(world.itempool, [original[1]])
        self.assertFalse(world.state.items)

    def test_duplicate_plans_need_real_copies_and_fail_without_partial_changes(self):
        world, locations = room({LEFT: HOOK, RIGHT: HOOK}, [HOOK, BOW])
        original = tuple(world.itempool)
        with self.assertRaisesRegex(ValueError, "not enough pool copies"):
            apply_item_plando(world, sweep)
        self.assertEqual(tuple(world.itempool), original)
        self.assertTrue(all(location.item is None for location in locations.values()))

    def test_disabled_or_forbidden_check_is_rejected_before_reservation(self):
        for disabled in (True, False):
            with self.subTest(disabled=disabled):
                world, locations = room({LEFT: HOOK, RIGHT: BOW}, [HOOK, BOW])
                if disabled:
                    world.worlds[1].moved.remove(RIGHT)
                else:
                    locations[RIGHT].item_rule = lambda _item: False
                with self.assertRaises(ValueError):
                    apply_item_plando(world, sweep)
                self.assertTrue(all(location.item is None for location in locations.values()))
                self.assertEqual(len(world.itempool), 2)

    def test_self_lock_and_two_item_cycle_are_rejected(self):
        for mapping, needs in (({LEFT: HOOK}, {LEFT: [HOOK]}),
                               ({LEFT: HOOK, RIGHT: BOW}, {LEFT: [BOW], RIGHT: [HOOK]})):
            with self.subTest(mapping=mapping):
                world, locations = room(mapping, [HOOK, BOW], needs)
                with self.assertRaisesRegex(ValueError, "locks progression"):
                    apply_item_plando(world, sweep)
                self.assertTrue(all(location.item is None for location in locations.values()))

    def test_reachable_planned_item_unlocks_later_plan(self):
        world, locations = room({LEFT: HOOK, RIGHT: BOW}, [HOOK, BOW], {RIGHT: [HOOK]})
        self.assertEqual(len(apply_item_plando(world, sweep)), 2)
        self.assertFalse(world.itempool)
        self.assertIsNotNone(locations[RIGHT].item)

    def test_partial_native_reservation_failure_restores_every_item_and_lock(self):
        world, locations = room({LEFT: HOOK, RIGHT: BOW}, [HOOK, BOW])
        def fail(_item):
            raise RuntimeError("reservation rejected")
        locations[RIGHT].place_locked_item = fail
        with self.assertRaises(RuntimeError):
            apply_item_plando(world, sweep)
        self.assertTrue(all(location.item is None and not location.locked for location in locations.values()))
        self.assertTrue(all(item.location is None for item in world.itempool))
        self.assertEqual(len(world.itempool), 2)


if __name__ == "__main__":
    unittest.main()
