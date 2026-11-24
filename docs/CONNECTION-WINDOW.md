# Desktop connection window

Open the **OOT Remake Archipelago** application and choose **Connection** from
the home screen. The controls open inside the same application, without a
console or a separate Python installation.

Choose an already prepared room, enter the server address and, if needed, its
password. The player and room are fixed by that room's mod. Preparing a new
`.apootrr` file through the application's **Set up a room** action is required
for a new room. That action prepares the mod and rebuilds the selected compatible
host when needed.

With Zelda closed, **Save** stores the connection settings for the next startup.
With the AP mod running, **Connect** and **Disconnect** control its existing
connection. Closing the window leaves Zelda and its connection running. The
window follows the prepared profile's game language, French or English.

**Keep** retains the password without displaying it. **Replace** saves a
new password; **Clear** deletes it. Windows DPAPI protects stored
passwords for the current Windows account. **Automatic connection** controls
whether the game connects at its next startup. Server addresses accept
`host:port`, `ws://host:port`, or `wss://host:port`.

Triforce's existing **Options → Archipelago** menu remains available and uses
the same settings and connection. Changes made in either interface are visible
in the other after applying them. Unsaved desktop edits are retained while the
window refreshes the connection status.

The experimental Hookshot 3.0.1 adapter provides **F1/Insert → Gameplay → AP
Server / AP Connect**, using Hookshot's native text fields and controller
navigation. Select its host in **Set up a room** first. Hookshot uses separate
profiles and saves from Triforce.

## Host support

The window does not depend on a host's menu renderer. It controls the AP bridge
inside the game through an authenticated service on the local PC. It never
opens a second Archipelago session or writes game saves.

The native installer supports **Triforce on Windows x64** and the pinned,
experimental **Hookshot 3.0.1 Windows** adapter. An updated
AP bridge is required for live desktop controls; use **Set up a room** in the
updated application to install it and perform any required game build. Offline
settings can be saved after closing the game. For an emulator or another
compatible process, use the separate **Other ports and emulators…** setup and
keep its window open. That runtime owns the external AP connection and uses
prepared native receipt/DeathLink resources. The native Connection page does
not control it. See [port compatibility](PORT-COMPATIBILITY.md) for the actual
Fritchii validation and the limits of other revisions.

## Development

The legacy standalone window remains available to developers using Python with
Tkinter. Run it from the source checkout with:

```powershell
pythonw distribution/Connect-Archipelago.pyw
```

Use `--profile <prepared-profile-directory>` for an isolated test profile. The
default profile directory is `%LOCALAPPDATA%\OOTRR-Archipelago`.

The native client publishes a versioned `connection-control.json` descriptor
with an ephemeral loopback port and a per-process credential protected by DPAPI
on Windows. Requests use bearer authentication, reject browser origins, and
contain bounded JSON bodies. The service delegates to the same connection
manager as the Triforce menu. An unavailable desktop service does not prevent
the game's existing menu or automatic connection from working.

Keep profile files and the control descriptor private. Neither is needed in a
public bug report. No password is included in connection status responses.
