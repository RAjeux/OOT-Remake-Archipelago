# Desktop connection window

Open **OOT-Remake-Archipelago-0.8.0-alpha.2.exe** and choose **Connection** from
the home screen. The controls open inside the same application, without a
console or a separate Python installation.

Choose an already prepared room, enter the server address and, if needed, its
password. The player and room are fixed by that room's mod. Preparing a new
`.apootrr` file through the application's **Set up a room** action is required
for a new room. That action prepares the mod and rebuilds Triforce when needed.

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

## Host support

The window does not depend on a host's menu renderer. It controls the AP bridge
inside the game through an authenticated service on the local PC. It never
opens a second Archipelago session or writes game saves.

The published native installer supports **Triforce on Windows x64**. An updated
AP bridge is required for live desktop controls; use **Set up a room** in the
updated application to install it and perform any required game build. Offline
settings can be saved after closing the game. The Hookshot prototype can use
this same interface when built with the
updated bridge. Other ports and emulators still need their own gameplay bridge;
this window alone does not add real-time item or DeathLink support to Fritchii.

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
