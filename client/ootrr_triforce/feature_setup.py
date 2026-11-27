"""Apply versioned additions only to a private, staged native AP mod."""
from .engine import run_engine
from .feature_settings import read_features


def prepare_features(romfs, mod, data):
    features = read_features(data.get("features"))
    if features is None:
        if data.get("additional_sources"):
            raise ValueError("Additional native sources require versioned feature settings.")
        return None
    request = {"features": features, "seed": data["seed_file"]["seed"],
               "settings": data["seed_file"]["settings"],
               "additional_sources": data.get("additional_sources", [])}
    protected = {}
    for source in data.get("network_sources", {}).values():
        for variant in source.get("variants", []):
            protected.setdefault(variant["file"], set()).add(variant["actor"])
    request["protected_sources"] = {name: sorted(actors) for name, actors in sorted(protected.items())}
    if features["settings"].get("dungeon_key_tracker"):
        caps = data.get("key_caps")
        if (not isinstance(caps, list) or len(caps) != 8
                or any(type(n) is not int or not 0 <= n <= 2**31 - 1 for n in caps)):
            raise ValueError("The room is missing its dungeon-key totals.")
        request["key_caps"] = list(caps)
    print(run_engine("features", request, romfs, mod).strip(), flush=True)
    return features


def prepare_cosmetics(romfs, mod, data):
    features = read_features(data.get("features"))
    if features is None:
        return None
    choices = features["settings"]
    if not (choices.get("cosmetic_color_mode", "off") != "off"
            or choices.get("shuffle_music", "off") != "off"
            or choices.get("shuffle_sfx", "off") != "off"):
        return features
    # A preparation retry must reproduce its appearance. It must never reroll
    # gameplay or replace the AP title graphic.
    seed = "AP-cosmetics-" + data["token"]
    print(run_engine("cosmetics", {"features": features, "seed": seed}, romfs, mod).strip(), flush=True)
    return features
