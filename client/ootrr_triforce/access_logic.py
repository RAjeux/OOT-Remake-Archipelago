"""Evaluate the native access graph exported with newly generated AP rooms.

Search and AST evaluation adapted from ootrando/ootrr Archipelago logic,
revision 4fa6e5a6 (GPL-3.0-or-later). Original notices remain in NOTICE.
The room keeps this graph; older rooms/engines retain their released wave rules.
"""
from collections import Counter, OrderedDict
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

AGES = ("adult", "child")

def num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return None


def same(a: Any, b: Any) -> bool:
    x, y = num(a), num(b)
    if x is not None and y is not None:
        return x == y
    return type(a) is type(b) and a == b


def member(a: Any, b: Any) -> bool:
    if isinstance(b, list):
        return any(same(a, x) for x in b)
    if isinstance(b, str):
        return isinstance(a, str) and a in b
    if isinstance(b, dict):
        return isinstance(a, str) and a in b
    return False


def compare(op: str, a: Any, b: Any) -> bool:
    if op == "==":
        return same(a, b)
    if op == "!=":
        return not same(a, b)
    if op == "in":
        return member(a, b)
    if op == "not in":
        return not member(a, b)
    x, y = num(a), num(b)
    if x is None or y is None:
        if isinstance(a, str) and isinstance(b, str):
            x, y = a, b
        else:
            return False
    if op == "<":
        return x < y
    if op == "<=":
        return x <= y
    if op == ">":
        return x > y
    return x >= y


def arith(op: str, a: Any, b: Any) -> Any:
    if type(a) is int and type(b) is int:
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            return None
        if op == "//":
            return a // b
        if op == "%":
            return a % b
        return a / b
    if isinstance(a, str) and isinstance(b, str) and op == "+":
        return a + b
    x, y = num(a), num(b)
    if x is None or y is None:
        return None
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0.0:
        return None
    if op == "/":
        return x / y
    if op == "//":
        return float(x // y)
    return x - y * (x // y)


class Ctx:
    __slots__ = ("cnt", "age", "tod", "region", "q")

    def __init__(self, cnt: List[int], age: Optional[int], tod: int, region: int, q: Optional["Search"]):
        self.cnt = cnt
        self.age = age
        self.tod = tod
        self.region = region
        self.q = q


def ev(n: Any, c: Ctx) -> bool:
    if n is True or n is False:
        return n
    t = n[0]
    if t == "h":
        return c.cnt[n[1]] >= n[2]
    if t == "and":
        for x in n[1]:
            if not ev(x, c):
                return False
        return True
    if t == "or":
        for x in n[1]:
            if ev(x, c):
                return True
        return False
    if t == "c":
        return bool(n[1])
    if t == "not":
        return not ev(n[1], c)
    if t == "any":
        return any(c.cnt[i] > 0 for i in n[1])
    if t == "all":
        return all(c.cnt[i] > 0 for i in n[1])
    if t == "ageis":
        return c.age is not None and AGES[c.age] == n[1]
    if t == "tod":
        f = n[1]
        if c.tod != 0:
            return c.tod & f != 0
        if ev(n[2], c):
            return True
        if c.q is None:
            return False
        if c.age is not None:
            return c.q.reach_tod(c.region, c.age, f)
        return any(c.q.reach_tod(c.region, a, f) for a in (0, 1))
    return bool(value(n, c))


def value(n: Any, c: Ctx) -> Any:
    if n is True or n is False:
        return n
    t = n[0]
    if t == "c":
        return n[1]
    if t == "i":
        return c.cnt[n[1]]
    if t == "d":
        return sum(1 for i in n[1] if c.cnt[i] > 0)
    if t == "age":
        return AGES[c.age] if c.age is not None else False
    if t == "neg":
        v = value(n[1], c)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        return -v
    if t == "bin":
        r = arith(n[1], value(n[2], c), value(n[3], c))
        return False if r is None else r
    if t == "cmp":
        return compare(n[1], value(n[2], c), value(n[3], c))
    if t == "if":
        return value(n[2], c) if ev(n[1], c) else value(n[3], c)
    if t == "list":
        return [value(x, c) for x in n[1]]
    return ev(n, c)


def deps(n: Any, out: set, tod: List[bool]) -> None:
    if n is True or n is False:
        return
    t = n[0]
    if t in ("h", "i"):
        out.add(n[1])
    elif t in ("any", "all", "d"):
        out.update(n[1])
    elif t in ("and", "or", "list"):
        for x in n[1]:
            deps(x, out, tod)
    elif t == "tod":
        tod[0] = True
        deps(n[2], out, tod)
    elif t in ("not", "neg"):
        deps(n[1], out, tod)
    elif t in ("cmp", "bin"):
        deps(n[2], out, tod)
        deps(n[3], out, tod)
    elif t == "if":
        deps(n[1], out, tod)
        deps(n[2], out, tod)
        deps(n[3], out, tod)


class World:
    def __init__(self, w: Dict[str, Any]):
        self.items: List[str] = [i["name"] for i in w["items"]]
        self.adv: List[bool] = [bool(i["adv"]) for i in w["items"]]
        self.event: List[bool] = [bool(i["event"]) for i in w["items"]]
        self.item_ix: Dict[str, int] = {}
        for k, n in enumerate(self.items):
            self.item_ix.setdefault(n, k)
        self.region_time: List[int] = [r["time"] for r in w["regions"]]
        self.region_name: List[str] = [r["name"] for r in w["regions"]]
        self.region_dungeon: List[Optional[str]] = [r.get("dungeon") for r in w["regions"]]
        self.region_exits: List[List[int]] = [r["exits"] for r in w["regions"]]
        self.region_locs: List[List[int]] = [r["locs"] for r in w["regions"]]
        self.exit_from: List[int] = [x["from"] for x in w["exits"]]
        self.exit_to: List[int] = [x["to"] for x in w["exits"]]
        self.exit_rule: List[Any] = [x["rule"] for x in w["exits"]]
        self.loc_name: List[str] = [l["name"] for l in w["locs"]]
        self.loc_region: List[int] = [l["region"] for l in w["locs"]]
        self.loc_rule: List[Any] = [l["rule"] for l in w["locs"]]
        self.loc_event: List[Optional[int]] = [l["event"] for l in w["locs"]]
        self.loc_ix: Dict[str, int] = {n: k for k, n in enumerate(self.loc_name)}
        self.goal: Any = w["goal"]
        self.start: List[Tuple[int, int]] = [(i, n) for i, n in w["start"]]
        self.root: int = w["root"]
        self.real: List[int] = list(w["real"])
        ne = len(self.exit_rule)
        self.users: List[List[int]] = [[] for _ in self.items]
        self.tod_users: List[int] = []
        rules = self.exit_rule + self.loc_rule
        for s, r in enumerate(rules):
            if r is True or r is False:
                continue
            found: set = set()
            tod = [False]
            deps(r, found, tod)
            for d in found:
                self.users[d].append(s)
            if tod[0]:
                self.tod_users.append(s)
        self.nexits = ne


class Search:
    def __init__(self, w: World, cnt: Optional[List[int]] = None):
        self.w = w
        self.cnt: List[int] = list(cnt) if cnt is not None else [0] * len(w.items)
        n = w.nexits + len(w.loc_name)
        r = len(w.region_name)
        self.visited: List[bool] = [False] * len(w.loc_name)
        self.reached: List[List[bool]] = [[False] * r, [False] * r]
        self.tods: List[List[int]] = [[0] * r, [0] * r]
        self.open: List[List[bool]] = [[False] * n, [False] * n]
        self.queued: List[List[bool]] = [[False] * n, [False] * n]
        self.queue: List[List[int]] = [[], []]
        self.dirty = False
        self.place: Dict[int, int] = {}
        self.adult_allowed = True
        for a in (0, 1):
            self._reach(a, w.root)

    def add(self, i: int, k: int = 1) -> None:
        self.cnt[i] += k
        self.dirty = True
        for s in self.w.users[i]:
            for a in (0, 1):
                self._push(a, s, False)

    def _push(self, a: int, s: int, op: bool) -> None:
        if op:
            self.open[a][s] = True
        if self.open[a][s] and not self.queued[a][s]:
            self.queued[a][s] = True
            self.queue[a].append(s)

    def _wanted(self, l: int) -> bool:
        if self.visited[l]:
            return False
        if self.w.loc_event[l] is not None:
            return True
        i = self.place.get(l)
        return i is not None and self.w.adv[i]

    def _reach(self, a: int, r: int) -> None:
        if self.reached[a][r]:
            return
        self.reached[a][r] = True
        self.dirty = True
        w = self.w
        self.tods[a][r] = w.region_time[r]
        for e in w.region_exits[r]:
            if not self.reached[a][w.exit_to[e]]:
                self._push(a, e, True)
        for l in w.region_locs[r]:
            if self._wanted(l):
                self._push(a, w.nexits + l, True)

    def _test(self, rule: Any, a: int, region: int) -> bool:
        if a == 0 and not self.adult_allowed:
            return False
        if rule is True or rule is False:
            return rule
        return ev(rule, Ctx(self.cnt, a, 0, region, self))

    def _step(self, a: int, s: int) -> None:
        if not self.open[a][s]:
            return
        w = self.w
        ne = w.nexits
        if s < ne:
            to = w.exit_to[s]
            if self.reached[a][to]:
                self.open[a][s] = False
                return
            if self._test(w.exit_rule[s], a, w.exit_from[s]):
                self.open[a][s] = False
                self._reach(a, to)
            return
        l = s - ne
        if self.visited[l]:
            self.open[a][s] = False
            return
        if not self._test(w.loc_rule[l], a, w.loc_region[l]):
            return
        self.visited[l] = True
        self.open[0][s] = False
        self.open[1][s] = False
        self.dirty = True
        e = w.loc_event[l]
        if e is not None:
            self.add(e, 1)
        else:
            i = self.place.get(l)
            if i is not None:
                self.add(i, 1)

    def _requeue_tod(self) -> bool:
        any_ = False
        for s in self.w.tod_users:
            for a in (0, 1):
                if self.open[a][s] and not self.queued[a][s]:
                    self._push(a, s, False)
                    any_ = True
        return any_

    def settle(self, place: Dict[int, int]) -> None:
        self.place = place
        ne = self.w.nexits
        for l in self.w.real:
            if not self._wanted(l):
                continue
            r = self.w.loc_region[l]
            for a in (0, 1):
                if self.reached[a][r] and not self.open[a][ne + l]:
                    self._push(a, ne + l, True)
        while True:
            moved = True
            while moved:
                moved = False
                for a in (0, 1):
                    q = self.queue[a]
                    if q:
                        s = q.pop()
                        self.queued[a][s] = False
                        self._step(a, s)
                        moved = True
                        break
            if self.dirty and self.w.tod_users:
                self.dirty = False
                if self._requeue_tod():
                    continue
            break

    def won(self) -> bool:
        return ev(self.w.goal, Ctx(self.cnt, None, 0, self.w.root, None))

    def loc_access(self, l: int) -> bool:
        r = self.w.loc_region[l]
        rule = self.w.loc_rule[l]
        return any(self.reached[a][r] and self._test(rule, a, r) for a in (0, 1))

    def reach_tod(self, region: int, a: int, flag: int) -> bool:
        if not self.reached[a][region]:
            return False
        if self.tods[a][region] & flag:
            return True
        return self._expand_tod(region, a, flag)

    def _expand_tod(self, goal: int, a: int, flag: int) -> bool:
        w = self.w
        t = list(self.tods[a])
        q: List[int] = []
        for r, f in enumerate(t):
            if f & flag:
                q.extend(w.region_exits[r])
        k = 0
        hit = False
        while k < len(q):
            x = q[k]
            k += 1
            to = w.exit_to[x]
            if not self.reached[a][to] or flag & ~t[to] == 0:
                continue
            rule = w.exit_rule[x]
            ok = rule if (rule is True or rule is False) else ev(rule, Ctx(self.cnt, a, flag, w.exit_from[x], None))
            if ok:
                t[to] |= flag
                if to == goal:
                    hit = True
                    break
                q.extend(w.region_exits[to])
        self.tods[a] = t
        return hit


def explore(w: World, place: Dict[int, int], extra: Iterable[Tuple[int, int]] = ()) -> Search:
    s = Search(w)
    for i, n in w.start:
        s.cnt[i] += n
    for i, n in extra:
        s.add(i, n)
    s.settle(place)
    return s


def validate(raw):
    """Reject malformed graph references before constructing a search object."""
    def fail():
        raise ValueError("Invalid native Archipelago access graph.")

    if not isinstance(raw, dict) or type(raw.get("schema")) is not int or raw["schema"] != 1:
        fail()
    w = raw.get("world")
    if not isinstance(w, dict):
        fail()
    tables = []
    for key in ("items", "regions", "exits", "locs"):
        rows = w.get(key)
        if not isinstance(rows, list) or len(rows) > 50000 or not all(isinstance(r, dict) for r in rows):
            fail()
        tables.append(rows)
    items, regions, exits, locs = tables
    if not items or not regions:
        fail()

    def ix(value, rows):
        if type(value) is not int or not 0 <= value < len(rows):
            fail()

    def indices(values, rows):
        if not isinstance(values, list) or len(values) > len(rows):
            fail()
        for value in values:
            ix(value, rows)
        if len(set(values)) != len(values):
            fail()

    def name(value):
        if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
            fail()

    for rows in (items, regions, locs):
        names = []
        for row in rows:
            name(row.get("name"))
            names.append(row["name"])
        if len(set(names)) != len(names):
            fail()
    for row in items:
        if type(row.get("adv")) is not bool or type(row.get("event")) is not bool:
            fail()
    budget = [300000]

    def ast(n, depth=0):
        budget[0] -= 1
        if depth > 128 or budget[0] < 0:
            fail()
        if type(n) is bool:
            return
        if not isinstance(n, list) or not n or not isinstance(n[0], str):
            fail()
        op = n[0]
        arities = {"c": 2, "h": 3, "i": 2, "d": 2, "any": 2, "all": 2,
                   "age": 1, "ageis": 2, "tod": 3, "not": 2, "neg": 2,
                   "and": 2, "or": 2, "list": 2, "cmp": 4, "bin": 4, "if": 4}
        if len(n) != arities.get(op):
            fail()
        if op == "c":
            if not isinstance(n[1], (str, bool, int, float, list, dict)) and n[1] is not None:
                fail()
            if isinstance(n[1], float) and not math.isfinite(n[1]):
                fail()
        elif op in ("h", "i"):
            ix(n[1], items)
            if op == "h" and (type(n[2]) is not int or not 0 <= n[2] <= 1000000):
                fail()
        elif op in ("any", "all", "d"):
            indices(n[1], items)
        elif op == "ageis":
            if n[1] not in AGES:
                fail()
        elif op == "tod":
            if type(n[1]) is not int or not 0 < n[1] <= 3:
                fail()
            ast(n[2], depth + 1)
        elif op in ("not", "neg"):
            ast(n[1], depth + 1)
        elif op in ("and", "or", "list"):
            if not isinstance(n[1], list):
                fail()
            for child in n[1]:
                ast(child, depth + 1)
        elif op in ("cmp", "bin"):
            operators = ("==", "!=", "<", "<=", ">", ">=", "in", "not in") if op == "cmp" else ("+", "-", "*", "/", "//", "%")
            if n[1] not in operators:
                fail()
            ast(n[2], depth + 1)
            ast(n[3], depth + 1)
        elif op == "if":
            for child in n[1:]:
                ast(child, depth + 1)

    ix(w.get("root"), regions)
    for rid, row in enumerate(regions):
        if type(row.get("time")) is not int or not 0 <= row["time"] <= 3:
            fail()
        indices(row.get("exits"), exits)
        indices(row.get("locs"), locs)
        if any(exits[e].get("from") != rid for e in row["exits"]):
            fail()
        if any(locs[l].get("region") != rid for l in row["locs"]):
            fail()
    for eid, row in enumerate(exits):
        ix(row.get("from"), regions)
        ix(row.get("to"), regions)
        if eid not in regions[row["from"]]["exits"]:
            fail()
        ast(row.get("rule"))
    for lid, row in enumerate(locs):
        ix(row.get("region"), regions)
        if lid not in regions[row["region"]]["locs"]:
            fail()
        if row.get("event") is not None:
            ix(row["event"], items)
        ast(row.get("rule"))
    ast(w.get("goal"))
    indices(w.get("real"), locs)
    if set(w["real"]) != {i for i, row in enumerate(locs) if row.get("event") is None}:
        fail()
    start = w.get("start")
    if not isinstance(start, list) or len(start) > 50000:
        fail()
    for row in start:
        if not isinstance(row, list) or len(row) != 2:
            fail()
        ix(row[0], items)
        if type(row[1]) is not int or not 0 <= row[1] <= 1000000:
            fail()
    fixed = raw.get("fixed")
    if not isinstance(fixed, list) or len(fixed) > len(locs):
        fail()
    fixed_ids = set()
    for row in fixed:
        if not isinstance(row, list) or len(row) != 2:
            fail()
        ix(row[0], locs)
        ix(row[1], items)
        if row[0] in fixed_ids or locs[row[0]].get("event") is not None:
            fail()
        fixed_ids.add(row[0])
    sources = raw.get("sources")
    if not isinstance(sources, dict) or len(sources) > 50000:
        fail()
    selected = set()
    for key, values in sources.items():
        name(key)
        indices(values, locs)
        if not values or any(v in fixed_ids or locs[v].get("event") is not None for v in values):
            fail()
        if selected.intersection(values):
            fail()
        selected.update(values)
    if raw.get("master_sword") is not None:
        ix(raw["master_sword"], locs)
    optional = raw.get("optional", [])
    if (not isinstance(optional, list) or not all(isinstance(n, str) and n in sources for n in optional)
            or len(set(optional)) != len(optional)):
        fail()
    required = raw.get("required", {})
    if (not isinstance(required, dict) or len(required) > len(items) + 1
            or any(not isinstance(n, str) or type(k) is not int or not 0 < k <= 1000000
                   for n, k in required.items())):
        fail()
    return raw


class Sweep:
    __slots__ = ("reach", "won")

    def __init__(self, reach, won):
        self.reach = frozenset(reach)
        self.won = bool(won)


KEY_DUNGEONS = ("Forest Temple", "Fire Temple", "Water Temple", "Shadow Temple",
                "Spirit Temple", "Bottom of the Well", "Gerudo Training Ground", "Ganons Castle")
MAX_KEY_TOTAL = 2**31 - 1


def key_caps(raw, pool):
    """Count owned keys everywhere, retaining native fixed and starting keys."""
    validate(raw)
    w = raw["world"]
    totals = Counter(pool)
    seen = set()
    for location, item in raw["fixed"]:
        # A native reward shared by the child/adult map has one source. The
        # compiler disambiguates its access aliases with " @ <region>".
        base = w["locs"][location]["name"].split(" @ ", 1)[0]
        identity = base, item
        if identity not in seen:
            seen.add(identity)
            totals[w["items"][item]["name"]] += 1
    for item, count in w["start"]:
        totals[w["items"][item]["name"]] += count
    result = [totals["Small Key (" + dungeon + ")"] for dungeon in KEY_DUNGEONS]
    if any(not 0 <= n <= MAX_KEY_TOTAL for n in result):
        raise ValueError("Invalid total number of dungeon keys.")
    return result


class AccessLogic:
    """Bounded memoized native search for one room's stable AP identities."""
    def __init__(self, raw, *, master_sword=False, optional=None, required=None):
        self.raw = validate(raw)
        self.world = World(raw["world"])
        self.fixed = dict(raw["fixed"])
        self.routes = dict(raw["sources"])
        self.master_sword = bool(master_sword)
        if self.master_sword:
            pedestal = raw.get("master_sword")
            if pedestal is None:
                raise ValueError("Master Sword shuffle requires a native pedestal access rule.")
            self.routes["ToT Master Sword"] = [pedestal]
        self.optional = frozenset(raw.get("optional", ()) if optional is None else optional)
        if not self.optional <= self.routes.keys():
            raise ValueError("Optional sources have no native access rule.")
        self.required = Counter(raw.get("required", {}) if required is None else dict(required))
        if optional is not None or required is not None:
            self.raw = dict(raw, optional=sorted(self.optional), required=dict(self.required))
            validate(self.raw)
        self.names = tuple(sorted({n for n, adv, event in zip(self.world.items, self.world.adv, self.world.event)
                                   if adv and not event} | set(self.required)
                                  | ({"Master Sword"} if master_sword else set())))
        self._cache = OrderedDict()

    def sweep(self, held):
        key = tuple(held.get(n, 0) for n in self.names)
        result = self._cache.get(key)
        if result is not None:
            self._cache.move_to_end(key)
            return result
        w = self.world
        # Counts are installed before opening root exits. This also handles
        # item-free true rules and the separate shuffled Master Sword gate.
        counts = [0] * len(w.items)
        for i, n in w.start:
            counts[i] += n
        for name, n in zip(self.names, key):
            i = w.item_ix.get(name)
            if i is not None:
                counts[i] += n
        s = Search(w, counts)
        s.adult_allowed = not self.master_sword or held.get("Master Sword", 0) > 0
        s.settle(self.fixed)
        reached = {name for name, locs in self.routes.items() if any(s.loc_access(l) for l in locs)}
        if all(held.get(n, 0) >= k for n, k in self.required.items()):
            reached.update(self.optional)
        result = Sweep(reached, s.won() and s.adult_allowed)
        self._cache[key] = result
        if len(self._cache) > 256:
            self._cache.popitem(last=False)
        return result

    def state(self, state, player):
        if hasattr(state, "prog_items"):
            held = state.prog_items[player]
        elif hasattr(state, "count"):
            held = {name: state.count(name, player) for name in self.names}
        else:
            held = state.counts
        return self.sweep(held)
