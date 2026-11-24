# Signed application updates

The application checks releases from `RAjeux/OOT-Remake-Archipelago`. It accepts
an automatic update only when the release provides `SHA256SUMS.txt` and an
Ed25519 signature in `SHA256SUMS.txt.sig`, verified against the public key
compiled into `client/ootrr_triforce/update_key.py`. Existing unsigned releases
remain ordinary manual downloads. A checksum by itself is not authentication.

The download is staged and checked before the executable is replaced. The
previous executable is retained as `.previous`; a failed replacement restores
it. Game files, mods, room profiles and saves are outside the update transaction.

## Publisher

Install `requirements-publisher.txt` in a publisher-only Python environment.
The player application needs no cryptographic signing dependency.

`python tools/sign_release.py provision` creates a real signing key outside the
repository and writes only its public verification key to the source tree. The
private key is encrypted by Windows DPAPI and its directory grants access to
the current account. Running provisioning again reuses the established key;
it does not rotate or replace it.

After building the final release files and their exact `SHA256SUMS.txt`, run:

```text
python tools/sign_release.py sign path/to/SHA256SUMS.txt
```

The tool checks every named asset against its checksum, verifies that the key
matches the checked-in public key, signs the unchanged checksum bytes, and
checks the result using the player's verifier. Publish the `.sig` alongside
the checksum list and the original assets. Never publish a private key, the
publisher directory or a DPAPI-protected key file.

DPAPI recovery requires the original Windows account's protected credentials;
copying its encrypted key file to another account is insufficient. Keep a
protected backup of that account's recovery material and publisher directory
outside the repository. Loss of the private key requires an explicit trust-key
migration through an already trusted update or a fresh manual installation.
Changing a public key is not an ordinary release update.
