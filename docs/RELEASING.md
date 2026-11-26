# Maintaining releases

Ordinary contributions do not change `VERSION` or overwrite release references.
Pull-request and `main` CI verify a development candidate against its current
sources. A maintainer makes a release separately; pushes of `v*` tags also run
the immutable reference check, and the tag must equal `v` followed by `VERSION`.

## Prepare a new version

1. Start from reviewed source with green CI. Choose a new, unused version in
   `VERSION` and update the player download links and release notes. Do not
   reuse an existing tag or replace its reference.
2. Rebuild the native DLL/digest and WASM if their sources changed. The defaults
   of `tools/build.py` and `tools/build_app.py` reuse supplied binaries; they do
   not compile Go or Rust automatically. Follow [development setup](DEVELOPMENT.md#rebuild-components).
3. Run the relevant [test matrix](TESTING.md). Include the fresh-engine checks,
   protocol cases, private generation and game observation appropriate to the
   change. Record unavailable checks and distinguish models from gameplay.
4. Assemble and validate the new source package:

   ```powershell
   .\.venv\Scripts\python.exe tools/build.py
   .\.venv\Scripts\python.exe tools/verify_candidate.py
   .\.venv\Scripts\python.exe tools/verify_release.py --record-reference
   .\.venv\Scripts\python.exe tools/verify_release.py
   ```

   Recording uses exclusive creation. Review and commit the **new**
   `tests/reference-<version>.json`; keep all previously published references.
5. Build the Windows player application with `requirements-app.txt` and
   `tools/build_app.py`, then inspect it using `tools/verify_app.py`. Run the
   frozen `--self-test` with private `LOCALAPPDATA` and `APPDATA`, inspect its
   actual UI when affected, and check that no game or personal data is packaged.

Keep generated files in ignored `build/` and `dist/`. Publish the standalone
EXE as the normal player download; the developer ZIP is a separate artifact.

## Tag and publish

Commit the version, source changes, release notes and new reference. Let normal
CI pass, then create an annotated `v<version>` tag on that exact commit. Push
the tag and wait for its release-reference check and other checks to pass
before publishing the release. Alpha versions remain GitHub prereleases.

The launcher updater expects these three assets together:

| Asset | Meaning |
| --- | --- |
| `OOT-Remake-Archipelago-<version>.exe` | Verified Windows x64 standalone application. |
| `ootrr_remake.apworld` | The same APWorld embedded in that application. |
| `SHA256SUMS.txt` | SHA-256 of the EXE and APWorld, one `hash  filename` entry per line. |

Write the checksum manifest as UTF-8 **without a byte-order mark**. Use exact
filenames and the reviewed artifact bytes. Upload and verify all assets in a
draft before making the release public. The updater checks these hashes and
Windows product/version metadata, and chooses the most recently published
eligible release before comparing semantic versions.

Download the public assets anonymously after publication and compare their
digests with the reviewed files. Verify that a previous supported launcher
offers the new release and that the new version reports itself as current.
Do not overwrite published assets or move a published tag to another commit.

## Auditing an existing release

Use the exact tagged source in a separate checkout or worktree to rebuild and
run `tools/verify_release.py`. An evolving `main` intentionally differs from
the latest published reference, even while its `VERSION` has not yet changed.
That difference is not a reason to rewrite an old reference or bump the version
for an ordinary contribution.

Player update compatibility and preservation of existing rooms are described
in [UPDATING.md](UPDATING.md). Keep that scope explicit in every release note.
