const fs = require("node:fs");
const path = require("node:path");
const { WASI } = require("node:wasi");
const [modulePath, command, game, mod] = process.argv.slice(2);
const preopens = command === "patch" || command === "shops"
  ? { "/game": game, "/mod": mod, "/load": path.dirname(path.dirname(mod)) } : {};
const wasi = new WASI({ version: "preview1", args: ["ootrr-ap", command], preopens, returnOnExit: true });
(async () => {
  const module = await WebAssembly.compile(fs.readFileSync(modulePath));
  const instance = await WebAssembly.instantiate(module, { wasi_snapshot_preview1: wasi.wasiImport });
  process.exitCode = wasi.start(instance);
})().catch(error => { console.error(error); process.exitCode = 1; });
