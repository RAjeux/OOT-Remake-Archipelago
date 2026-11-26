"""Shared desktop palette, accessible ttk controls and original vector branding."""
import math
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk


COLORS = {
    "bg": "#0d1719", "sidebar": "#101f22", "surface": "#16282b",
    "elevated": "#1c3336", "border": "#2b4244", "text": "#edf1e9",
    "muted": "#9aafaa", "gold": "#e3be71", "gold_hover": "#f0cf8b",
    "mint": "#83c5ad", "danger": "#f08c82",
}
FONT = ("Segoe UI", 10)
FIELD_FONT = ("Segoe UI", 11)


def _options(root):
    """Cover classic Tk widgets and the Combobox popdown with the same palette."""
    options = {
        # A global *Font also becomes an explicit ttk widget option and masks
        # its style's title/heading font. Restrict defaults to classic widgets.
        "*Menu.font": FONT, "*Text.font": FONT, "*Listbox.font": FONT,
        "*Entry.font": FIELD_FONT, "*Button.font": FONT, "*Spinbox.font": FIELD_FONT,
        "*Menu.background": COLORS["sidebar"], "*Menu.foreground": COLORS["text"],
        "*Menu.activeBackground": COLORS["elevated"], "*Menu.activeForeground": COLORS["gold"],
        "*Menu.disabledForeground": COLORS["muted"], "*Menu.relief": "flat",
        "*Menu.borderWidth": 1, "*Menu.tearOff": False,
        "*Text.background": COLORS["elevated"], "*Text.foreground": COLORS["text"],
        "*Text.insertBackground": COLORS["gold"], "*Text.selectBackground": COLORS["gold"],
        "*Text.selectForeground": COLORS["bg"], "*Text.highlightBackground": COLORS["border"],
        "*Text.highlightColor": COLORS["gold"], "*Text.borderWidth": 0,
        "*Text.highlightThickness": 1,
        "*Listbox.background": COLORS["elevated"], "*Listbox.foreground": COLORS["text"],
        "*Listbox.selectBackground": COLORS["gold"], "*Listbox.selectForeground": COLORS["bg"],
        "*Listbox.disabledForeground": COLORS["muted"], "*Listbox.borderWidth": 0,
        "*Listbox.highlightBackground": COLORS["border"], "*Listbox.highlightColor": COLORS["gold"],
        "*Listbox.highlightThickness": 1,
        "*Canvas.background": COLORS["bg"], "*Canvas.highlightThickness": 0,
        "*Entry.background": COLORS["elevated"], "*Entry.foreground": COLORS["text"],
        "*Entry.insertBackground": COLORS["gold"], "*Entry.selectBackground": COLORS["gold"],
        "*Entry.selectForeground": COLORS["bg"], "*Entry.disabledBackground": COLORS["surface"],
        "*Entry.disabledForeground": COLORS["muted"], "*Entry.readonlyBackground": COLORS["surface"],
        "*Entry.highlightBackground": COLORS["border"], "*Entry.highlightColor": COLORS["gold"],
        "*Button.background": COLORS["surface"], "*Button.foreground": COLORS["text"],
        "*Button.activeBackground": COLORS["elevated"], "*Button.activeForeground": COLORS["text"],
        "*Button.disabledForeground": COLORS["muted"], "*Button.highlightColor": COLORS["gold"],
    }
    for name, value in options.items():
        root.option_add(name, value)


def _button(style, name, *, background, foreground, hover, padding=(16, 10), bold=False):
    style.configure(name, background=background, foreground=foreground,
                    font=("Segoe UI", 10, "bold") if bold else FONT,
                    padding=padding, anchor="center", borderwidth=1, relief="flat",
                    bordercolor=background, lightcolor=background, darkcolor=background,
                    focuscolor=COLORS["bg"] if background == COLORS["gold"] else COLORS["gold_hover"],
                    focusthickness=1, focussolid=True)
    style.map(name,
              background=[("disabled", COLORS["surface"]), ("pressed", hover), ("active", hover)],
              foreground=[("disabled", COLORS["muted"])],
              bordercolor=[("focus", COLORS["gold"]), ("active", hover)],
              lightcolor=[("focus", COLORS["gold"]), ("active", hover)],
              darkcolor=[("focus", COLORS["gold"]), ("active", hover)])


def apply_theme(master):
    """Apply the shared theme once per Tcl interpreter and return its Style.

    Calling this for a dialog preserves application-specific style additions,
    keyboard focus and active widget state on windows already open.
    """
    root = master._root()
    target = master.winfo_toplevel()
    target.configure(background=COLORS["bg"])
    cached = getattr(root, "_ootrr_theme_style", None)
    if cached is not None:
        return cached
    style = ttk.Style(master)
    available = style.theme_names()
    for theme in ("clam", "alt", "default"):
        if theme in available:
            style.theme_use(theme)
            break
    c = COLORS
    _options(root)
    style.configure(".", background=c["bg"], foreground=c["text"], font=FONT,
                    bordercolor=c["border"], selectbackground=c["gold"], selectforeground=c["bg"])
    style.configure("TFrame", background=c["bg"])
    style.configure("App.Card.TFrame", background=c["surface"])
    style.configure("App.Sidebar.TFrame", background=c["sidebar"])
    style.configure("App.Inset.TFrame", background=c["elevated"])
    style.configure("TLabel", background=c["bg"], foreground=c["text"], font=FONT)
    labels = {
        "Title": (25, "bold", c["text"], c["bg"]),
        "Heading": (17, "bold", c["text"], c["bg"]),
        "Subheading": (12, "bold", c["text"], c["bg"]),
        "Muted": (10, "normal", c["muted"], c["bg"]),
        "Caption": (9, "normal", c["muted"], c["bg"]),
        "Eyebrow": (9, "bold", c["gold"], c["bg"]),
        "Card": (11, "normal", c["text"], c["surface"]),
        "CardHeading": (13, "bold", c["text"], c["surface"]),
        "CardMuted": (10, "normal", c["muted"], c["surface"]),
        "CardCaption": (9, "normal", c["muted"], c["surface"]),
        "Hero": (29, "bold", c["text"], c["surface"]),
        "Inset": (10, "normal", c["text"], c["elevated"]),
        "Sidebar": (10, "normal", c["text"], c["sidebar"]),
        "SidebarMuted": (9, "normal", c["muted"], c["sidebar"]),
        "Brand": (14, "bold", c["gold"], c["sidebar"]),
        "Status": (10, "bold", c["mint"], c["elevated"]),
        "Error": (10, "normal", c["danger"], c["surface"]),
    }
    for name, (size, weight, foreground, background) in labels.items():
        style.configure("App."+name+".TLabel", font=("Segoe UI", size, weight),
                        foreground=foreground, background=background)
    _button(style, "TButton", background=c["elevated"], foreground=c["text"], hover=c["border"])
    _button(style, "App.Primary.TButton", background=c["gold"], foreground=c["bg"],
            hover=c["gold_hover"], padding=(22, 13), bold=True)
    _button(style, "App.Action.TButton", background=c["elevated"], foreground=c["text"], hover=c["border"])
    _button(style, "App.Quiet.TButton", background=c["bg"], foreground=c["muted"], hover=c["surface"], padding=(12, 8))
    _button(style, "App.Nav.TButton", background=c["sidebar"], foreground=c["muted"], hover=c["surface"], padding=(16, 12))
    _button(style, "App.NavActive.TButton", background=c["elevated"], foreground=c["gold"], hover=c["border"], padding=(16, 12), bold=True)
    for name in ("App.Nav.TButton", "App.NavActive.TButton"):
        style.configure(name, anchor="w")
    _button(style, "TMenubutton", background=c["bg"], foreground=c["muted"], hover=c["surface"], padding=(12, 8))
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=c["elevated"], background=c["elevated"],
                        foreground=c["text"], insertcolor=c["gold"], selectbackground=c["gold"],
                        selectforeground=c["bg"], bordercolor=c["border"], lightcolor=c["border"],
                        darkcolor=c["border"], arrowcolor=c["muted"], padding=(10, 8), font=FIELD_FONT)
        style.map(name, fieldbackground=[("disabled", c["surface"]), ("readonly", c["elevated"])],
                  foreground=[("disabled", c["muted"]), ("readonly", c["text"])],
                  bordercolor=[("focus", c["gold"]), ("active", c["muted"])],
                  lightcolor=[("focus", c["gold"])], darkcolor=[("focus", c["gold"])],
                  arrowcolor=[("disabled", c["border"]), ("active", c["gold"])])
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=c["bg"], foreground=c["text"], font=FONT,
                        padding=(0, 5), focuscolor=c["gold"], focusthickness=1,
                        indicatorbackground=c["elevated"], indicatorforeground=c["bg"],
                        upperbordercolor=c["border"], lowerbordercolor=c["border"])
        style.map(name, background=[("active", c["bg"])], foreground=[("disabled", c["muted"])],
                  indicatorbackground=[("disabled", c["surface"]), ("selected", c["gold"])],
                  indicatorforeground=[("disabled", c["muted"])],
                  upperbordercolor=[("focus", c["gold"]), ("active", c["muted"])],
                  lowerbordercolor=[("focus", c["gold"]), ("active", c["muted"])])
        card = "App.Card."+name
        style.configure(card, background=c["surface"])
        style.map(card, background=[("active", c["surface"]), ("disabled", c["surface"])])
    for name in ("TLabelframe", "App.Card.TLabelframe"):
        style.configure(name, background=c["surface"], bordercolor=c["border"], borderwidth=1, relief="solid")
        style.configure(name+".Label", background=c["surface"], foreground=c["muted"], font=("Segoe UI", 10, "bold"))
    style.configure("TSeparator", background=c["border"])
    style.configure("TPanedwindow", background=c["bg"])
    style.configure("TNotebook", background=c["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=c["surface"], foreground=c["muted"], padding=(16, 9))
    style.map("TNotebook.Tab", background=[("selected", c["elevated"]), ("active", c["surface"])],
              foreground=[("selected", c["gold"]), ("active", c["text"])])
    style.configure("Treeview", background=c["elevated"], fieldbackground=c["elevated"], foreground=c["text"],
                    bordercolor=c["border"], borderwidth=0, rowheight=30, font=FONT)
    style.map("Treeview", background=[("selected", "!focus", c["border"]), ("selected", c["gold"])],
              foreground=[("selected", "!focus", c["text"]), ("selected", c["bg"])])
    style.configure("Treeview.Heading", background=c["surface"], foreground=c["muted"],
                    font=("Segoe UI", 9, "bold"), padding=(9, 8), relief="flat")
    style.map("Treeview.Heading", background=[("active", c["elevated"])], foreground=[("active", c["gold"])])
    for orient in ("Horizontal", "Vertical"):
        style.configure(orient+".TProgressbar", background=c["mint"], troughcolor=c["elevated"],
                        bordercolor=c["elevated"], lightcolor=c["mint"], darkcolor=c["mint"], thickness=7)
        style.configure(orient+".TScrollbar", background=c["border"], troughcolor=c["surface"],
                        bordercolor=c["surface"], lightcolor=c["border"], darkcolor=c["border"],
                        arrowcolor=c["muted"], arrowsize=11, borderwidth=0, relief="flat")
        style.map(orient+".TScrollbar", background=[("active", c["muted"])],
                  arrowcolor=[("active", c["gold"]), ("disabled", c["border"])])
        style.configure(orient+".TScale", background=c["gold"], troughcolor=c["elevated"],
                        bordercolor=c["border"], lightcolor=c["gold"], darkcolor=c["gold"])
    style.configure("TSizegrip", background=c["bg"])
    root._ootrr_theme_style = style
    return style


def _dark_title_bar(window):
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes as w
        if not window.winfo_exists():
            return
        user = ctypes.WinDLL("user32.dll", winmode=0x800, use_last_error=True)
        user.GetAncestor.argtypes = [w.HWND, w.UINT]
        user.GetAncestor.restype = w.HWND
        handle = user.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
        dwm = ctypes.WinDLL("dwmapi.dll", winmode=0x800, use_last_error=True)
        dwm.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, w.LPCVOID, w.DWORD]
        dwm.DwmSetWindowAttribute.restype = w.LONG
        enabled = w.BOOL(True)
        for attribute in (20, 19):
            if dwm.DwmSetWindowAttribute(handle, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0:
                break
    except (AttributeError, OSError, tk.TclError):
        pass


def set_window_icon(master):
    """Reuse the packaged icon and request a dark Windows title bar if supported."""
    root, window = master._root(), master.winfo_toplevel()
    if not getattr(window, "_ootrr_chrome_scheduled", False):
        window._ootrr_chrome_scheduled = True
        def apply_chrome():
            window._ootrr_chrome_after = None
            _dark_title_bar(window)
        def cancel_chrome(event):
            if event.widget is not window:
                return
            pending = getattr(window, "_ootrr_chrome_after", None)
            if pending is not None:
                try:
                    window.after_cancel(pending)
                except tk.TclError:
                    pass
                window._ootrr_chrome_after = None
        window._ootrr_chrome_after = window.after_idle(apply_chrome)
        window.bind("<Destroy>", cancel_chrome, add="+")
    image = getattr(root, "_ootrr_app_icon", None)
    if image is None:
        from .app_runtime import resource_root
        candidates = (resource_root()/"assets/icon.png", Path(__file__).resolve().parents[2]/"assets/icon.png")
        for path in candidates:
            if path.is_file():
                try:
                    image = tk.PhotoImage(master=root, file=path)
                    root._ootrr_app_icon = image
                    break
                except (OSError, tk.TclError):
                    continue
    if image is None:
        return False
    try:
        window.iconphoto(True, image)
        return True
    except tk.TclError:
        return False


def draw_brand(canvas, x, y, size):
    """Draw an original golden triangle emblem with connected AP orbit nodes.

    x/y are the top-left of a square. Returned canvas item IDs let a caller
    remove or move this instance without affecting the canvas' other artwork.
    """
    if not math.isfinite(size) or size <= 0:
        return []
    ids = []
    cx, cy, radius = x+size*.5, y+size*.51, size*.44
    ids.append(canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius,
                                 outline=COLORS["border"], width=max(1, size*.012)))
    nodes = []
    for angle in (-102, 18, 138):
        radians = math.radians(angle)
        nodes.append((cx+math.cos(radians)*radius, cy+math.sin(radians)*radius))
    for first, second in ((0, 1), (1, 2), (2, 0)):
        ids.append(canvas.create_line(*nodes[first], *nodes[second], fill=COLORS["border"], width=max(1, size*.012)))
    left, top, width, height = x+size*.23, y+size*.23, size*.54, size*.468
    for points in ((left+width*.5,top,left+width*.25,top+height*.5,left+width*.75,top+height*.5),
                   (left+width*.25,top+height*.5,left,top+height,left+width*.5,top+height),
                   (left+width*.75,top+height*.5,left+width*.5,top+height,left+width,top+height)):
        ids.append(canvas.create_polygon(*points, fill=COLORS["gold"], outline=""))
    dot = max(2, size*.035)
    for index, (nx, ny) in enumerate(nodes):
        ids.append(canvas.create_oval(nx-dot, ny-dot, nx+dot, ny+dot,
                                     fill=COLORS["mint"] if index == 1 else COLORS["gold"],
                                     outline=COLORS["sidebar"], width=max(1, size*.01)))
    return ids
