"""Compile and execute the native C/C++ bridge models without game resources."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ("test_restore_host", "test_menu_bridge", "test_menu_editing", "test_language_host",
          "test_link", "test_deathlink_host")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", help="C compiler, also accepted through CC.")
    parser.add_argument("--cxx", help="C++ compiler, also accepted through CXX.")
    args = parser.parse_args()
    environment = dict(os.environ)
    cc = args.cc or environment.get("CC") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        parser.error("Install GCC or Clang, or select a compiler with --cc or CC.")
    environment["CC"] = cc
    if args.cxx:
        environment["CXX"] = args.cxx
    for name in CHECKS:
        print("> tests/" + name + ".py", flush=True)
        subprocess.run([sys.executable, str(ROOT / "tests" / (name + ".py"))],
                       cwd=ROOT, env=environment, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
