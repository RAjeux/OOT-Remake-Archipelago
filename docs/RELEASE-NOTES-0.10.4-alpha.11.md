# OOT Remake Archipelago 0.10.4 alpha 11: import and edit player YAMLs

Choose **Create YAML → Import YAML…**, open an existing `.yaml` or `.yml`,
then **Choose settings…**. The launcher loads the player name and compatible
settings, allowing small changes without starting again. **Save YAML** proposes
a separate `-modified.yaml` copy.

Untouched values retain their meaning, including weighted selections, random
options, Archipelago starting inventory, local items and extra metadata.
Weighted or otherwise protected fields show **Imported value kept**; use
**Replace** to choose a new value. Import details lists preserved settings and
compatibility changes. **New configuration** starts with current defaults.

Older native `OOTRR1-` settings codes are decoded with the bundled engine.
Active obsolete settings require review before conversion, and invalid values
must be replaced before export. The discontinued Full-network format is not
re-enabled. YAML comments and formatting are regenerated. Random settings are
preserved without guaranteeing every possible generated combination is valid.

Backend tests cover preservation, legacy decoding, aliases, weighted choices,
invalid input and generator normalization. Tk integration tests exercise
import, editing, separate-file export, cancellation and both interface
languages. Frozen application verification also exercises YAML import and the
actual legacy decoder. These checks use isolated data and do not start Zelda.

This is a launcher-only feature. Game code, generation rules, room placements
and saves are unchanged. Continue an existing native 0.10 room with the same
player file and save; this update itself needs no game preparation or new room.
Changing a YAML only affects a future generation.
