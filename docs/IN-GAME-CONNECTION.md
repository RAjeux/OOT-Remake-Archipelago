# Connect from Zelda's menu

After preparing a room's mod and rebuilding Triforce, open Zelda's **Options** screen from the title or the pause menu and select **Archipelago**. No console is needed for ordinary connection changes.

Enter the server address, such as `archipelago.gg:38281` or `127.0.0.1:38281`, then choose **Connect**. Explicit `ws://` and `wss://` addresses are supported. The panel shows the prepared player, room, connection state, and errors. The game language selects French or English.

Select a text field to type with the keyboard or the controller's on-screen keyboard. Confirm accepts the edit; Back cancels it. Closing the panel releases text input and returns control to the game menu.

The password field is masked. **Keep saved** reuses the existing password without displaying it. Typing a replacement selects **Save new**; **Remove saved** clears it. Changes are stored when choosing Connect, with Windows DPAPI protecting saved passwords. A password that cannot be read on this PC can be replaced or removed from this panel.

**Automatic connection** controls startup and defaults to enabled for existing profiles. Its setting is saved with Connect. **Disconnect** stops the current connection and its retries; it retains the save, received-item index, and offline checks. Connect can resume the same room without restarting Zelda.

The prepared player is read-only. A server address does not select a new seed or another player's inventory. A room or player mismatch is rejected. Prepare the corresponding `.apootrr` mod before playing a different room.

## Upgrade

The connection menu changes the native DLL and Triforce renderer. Extract the complete release, run `Configure-Archipelago.cmd` for the existing player file, then use **Build again** in Triforce Setup. Both the executable and `triforce_vk.dll` must be rebuilt. The setup tool preserves source backups and reports incompatible host versions before changing their sources.

Initial room generation and mod preparation remain separate from connection controls. `Observe-Archipelago.cmd` remains available for diagnostics.

The separate [desktop connection window](CONNECTION-WINDOW.md) controls the same
client and settings. Triforce's embedded menu remains available with its existing
keyboard, mouse, and controller navigation.

## Implementation references

The implementation uses Triforce's existing embedded Options screen, text-input queue, game fonts, and controller navigation. It adds an original UI helper and an asynchronous connection manager while retaining the client and its room/save binding.

The connection and navigation patterns were researched in [MMRecompRando's AP menu](https://github.com/RecompRando/MMRecompRando/blob/27ed1ad0b7113e5e97564aac636852a5aff622f8/src/apconnect_menu.c), [Shipwright AP's settings panel](https://github.com/jeromkiller/Shipwright_archipellago/blob/aff37bfda895da98678e8a3f27e4e25868fc3dba/soh/soh/Network/Archipelago/ArchipelagoSettingsWindow.cpp), and [Zelda64Recomp's focus/navigation](https://github.com/Zelda64Recomp/Zelda64Recomp/blob/b65c482ed672258eb684ab94a4e8c8aa662615ee/src/ui/ui_state.cpp). Their UI libraries are different from Triforce's; no third-party implementation was copied.
