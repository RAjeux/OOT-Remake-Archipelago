# 0.10.1-alpha.3 — Triforce 0.8.0 compatibility

The installer now supports **Triforce 0.8.0's menu hooks**, including resolution
editing and tuning overlays. It also detects host-source and tool-version
updates so an older compiled AP host is rebuilt when necessary. Older supported
menu layouts and valid current builds retain their existing behavior.

Download `OOT-Remake-Archipelago-0.10.1-alpha.3.exe`. Close Zelda and Triforce
Setup, let the host update finish, then use **Set up a room** with the same
native 0.10-line `.apootrr` file. Setup prepares the mod and rebuilds the host
when required. **No new room or new save is needed for this fix.** Existing
placements, check catalogues and saves are retained.

Room generation, item IDs, settings values and defaults are unchanged. The
expanded 0.10.1 catalogue still requires a newly generated room and dedicated
save if the existing room did not already include those checks. Experimental
0.12 Full files are not converted by this compatibility update.

Automated checks cover menu patching and idempotence, native text-input paths,
read-only installation discovery, cache invalidation and private compilation
of the updated host C source. This is build and regression evidence, not a
complete manual gameplay playthrough of Triforce 0.8.0. The existing alpha
presentation and gameplay-validation limits remain; see
[test coverage](TEST-COVERAGE.md).
