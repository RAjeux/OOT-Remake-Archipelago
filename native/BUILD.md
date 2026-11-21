# Archipelago native client

The Go library connects to Archipelago through WebSocket. The Windows host bridge is compiled in Triforce and looks up the active RomFS marker through its mod loader. It checks the SHA-256 of the library beside that mod's RomFS before loading it. Game data access happens on Link's update thread.

For a Windows x64 build, use Go with cgo enabled and a compatible x64 C compiler. The vendored modules allow an offline build.

    go build -mod=vendor -buildvcs=false -trimpath -ldflags="-s -w" -buildmode=c-shared -o archipelago.dll .
    python write_digest.py archipelago.dll

Ship the DLL and its corresponding digest header together. Changes to the digest or the bridge require a new local game build. The compiled game and its assets are produced on the player's PC.

The host must provide `hos_desired_language()`. The bridge uses the selected Triforce game language for automatic French or English runtime text; unsupported languages fall back to English. This does not change AP item IDs, slot names, or chat messages.

The embedded connection page also installs `ootrr_ap_menu.inc` beside `gpu/vk/vk_menu.cpp`, patched by `client/ootrr_triforce/menu_setup.py`. Rebuild the executable and renderer together. The renderer discovers the host's `ootrr_ap_menu16` export without changing Triforce's Vulkan host ABI. The tab is shown only for an active, verified AP runtime.

The DLL exports `AP_ConnectionInfo(char*, int)`, `AP_Connect(char*, char*, int, int)`, and `AP_Disconnect()`. The snapshot contains server, bound player/room, safe connection state/error codes, password-presence and automatic-connection flags, and the effective language. It never returns a password. Connect accepts password modes 0 (keep), 1 (replace and protect), or 2 (clear), and a startup-connection flag of 0 or 1. Network dialing and synchronization run asynchronously.

Connection changes retain the same client, profile lock, item history, saved cursor, and check journal. Only connection fields in `native-session.json` are replaced atomically; seed fields and unknown metadata are preserved. A cancelled connection cannot publish packets into its replacement session. DeathLink is cleared across disconnection because it is a live event.

The optional desktop window uses `control.go`, started after `AP_Start` acquires
the profile lock. Its authenticated HTTP service binds only to an ephemeral
`127.0.0.1` port. The per-process bearer in `connection-control.json` is protected
with Windows DPAPI; POSIX development uses file mode 0600. Browser origins,
proxy requests, malformed commands, and oversized bodies are rejected. The
service calls the same `connect`, `disconnect`, and `connectionInfo` methods as
the menu. No additional host export or renderer patch is needed for this
interface. Control-service startup failure is nonfatal to the game connection.

See [the desktop guide](../docs/CONNECTION-WINDOW.md) for the player workflow.
