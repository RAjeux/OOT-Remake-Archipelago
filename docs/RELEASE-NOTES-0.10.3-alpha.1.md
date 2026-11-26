# 0.10.3 alpha 1: a redesigned desktop launcher

The launcher now uses a shared dark palette with gold primary actions, readable
typography and an original vector emblem. A persistent sidebar gives access to
the prepared room, setup, YAML creation, connection controls and APWorld install.
Room preparation groups the player file, game and server into three cards;
its actions remain visible while the form scrolls. Keyboard focus reveals fields
below the fold, and Ctrl+1/2/3 switches the main pages without discarding a draft.

The YAML editor retains all 97 controls and their existing values and rules.
Search, categories and explanations have clearer spacing and hierarchy. The
summary adapts to window size, and keyboard navigation scrolls controls into view.
Connection and update windows share the same theme, card layout and action
hierarchy. Release notes are readable and selectable in the update window.

This is a desktop interface update. The native library, engine, AP item/location
IDs, generation rules and prepared-resource revision are unchanged. A room
already prepared with current 0.10.2 resources remains playable; it needs no new
YAML, room, save or preparation for this visual update. Other older room updates
still follow the existing preparation checks. Superseded experimental Full
player files are not converted by changing the launcher.

The 0.10.2 launcher can install this version with its update button, including an
optional APWorld replacement. Older launchers without the updater require one
manual download. This remains an alpha; the existing gameplay validation limits
are unchanged. See [the update guide](UPDATING.md) and [test coverage](TEST-COVERAGE.md).
