# Archipelago native client

The Go library connects to Archipelago through WebSocket. The Windows host bridge is compiled in Triforce and looks up the active RomFS marker through its mod loader. It checks the SHA-256 of the library beside that mod's RomFS before loading it. Game data access happens on Link's update thread.

For a Windows x64 build, use Go with cgo enabled and a compatible x64 C compiler. The vendored modules allow an offline build.

    go build -mod=vendor -buildvcs=false -trimpath -ldflags="-s -w" -buildmode=c-shared -o archipelago.dll .
    python write_digest.py archipelago.dll

Ship the DLL and its corresponding digest header together. Changes to the digest or the bridge require a new local game build. The compiled game and its assets are produced on the player's PC.

The host must provide `hos_desired_language()`. The bridge uses the selected Triforce game language for automatic French or English runtime text; unsupported languages fall back to English. This does not change AP item IDs, slot names, or chat messages.
