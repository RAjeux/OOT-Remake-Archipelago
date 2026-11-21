"""Double-click with Windows' Python windowed launcher; no console is needed."""
from pathlib import Path
import sys

bundle = Path(__file__).resolve().with_name("Client-OOT-Remake.pyz")
sys.path.insert(0, str(bundle if bundle.is_file() else Path(__file__).resolve().parents[1] / "client"))

if __name__ == "__main__":
    try:
        from ootrr_triforce.connection_window import main
        main()
    except Exception:
        # pythonw has no console. Show a fixed message, never raw exception text.
        text = ("Unable to open the Archipelago connection window. "
                "Keep this file beside Client-OOT-Remake.pyz and install Python with Tcl/Tk support.")
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Archipelago", 16)
        else:
            from tkinter import messagebox
            messagebox.showerror("Archipelago", text)
