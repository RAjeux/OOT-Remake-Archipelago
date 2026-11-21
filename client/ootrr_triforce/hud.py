"""An unintrusive Windows HUD pinned to the Triforce game window."""
from collections import deque
import json
import os
from pathlib import Path
import subprocess
import sys


class Hud:
    def __init__(self):
        self.child = None
        self.pending = deque()

    def notify(self, title, item, detail, kind):
        self.pending.append([title, item, detail, kind])
        self.flush()

    def start(self, pid):
        self.close()
        if os.name != "nt":
            return
        try:
            self.child = subprocess.Popen([sys.executable, str(Path(sys.argv[0]).resolve()), "--hud", str(pid)],
                                          stdin=subprocess.PIPE, encoding="utf-8", text=True)
        except OSError as err:
            print("Affichage des notifications indisponible :", err, flush=True)
        self.flush()

    def flush(self):
        if not self.child or self.child.poll() is not None:
            return
        try:
            while self.pending:
                self.child.stdin.write(json.dumps(self.pending[0]) + "\n")
                self.child.stdin.flush()
                self.pending.popleft()
        except (BrokenPipeError, OSError):
            self.close()

    def close(self):
        if self.child:
            try:
                self.child.stdin.close()
            except OSError:
                pass
            self.child = None


def overlay(pid):
    import ctypes as c
    from ctypes import wintypes as w
    import queue
    import threading
    import time
    import tkinter as tk
    user = c.WinDLL("user32", use_last_error=True)
    def api(name, result, *args):
        call = getattr(user, name)
        call.argtypes, call.restype = args, result
        return call
    try:
        api("SetProcessDpiAwarenessContext", w.BOOL, w.HANDLE)(c.c_void_p(-4))
    except AttributeError:
        user.SetProcessDPIAware()
    foreground = api("GetForegroundWindow", w.HWND)
    getpid = api("GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
    rect = api("GetClientRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
    screen = api("ClientToScreen", w.BOOL, w.HWND, c.POINTER(w.POINT))
    ancestor = api("GetAncestor", w.HWND, w.HWND, w.UINT)
    get_style = api("GetWindowLongW", w.LONG, w.HWND, c.c_int)
    set_style = api("SetWindowLongW", w.LONG, w.HWND, c.c_int, w.LONG)
    position = api("SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT)
    show = api("ShowWindow", w.BOOL, w.HWND, c.c_int)
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-alpha", 0.0)
    root.geometry("1x1+0+0")
    canvas = tk.Canvas(root, highlightthickness=0, bg="#142523")
    canvas.pack(fill="both", expand=True)
    root.update_idletasks()
    def configure_handle():
        handle = ancestor(root.winfo_id(), 2)
        set_style(handle, -20, get_style(handle, -20) | 0x08000000 | 0x00080000 | 0x80 | 0x20)
        return handle
    configure_handle()
    root.deiconify()
    root.update_idletasks()
    root.attributes("-alpha", .96)
    hwnd = configure_handle()
    show(hwnd, 0)
    inbox = queue.Queue()
    def read():
        try:
            for line in sys.stdin.buffer:
                inbox.put(json.loads(line))
        finally:
            inbox.put(None)
    threading.Thread(target=read, daemon=True).start()
    pending = deque()
    current = None
    remaining = 0.
    stamp = time.monotonic()
    last_width = None
    def draw(message, width):
        title, item, detail, kind = message
        color = "#efc676" if kind == "out" else "#8be5bf"
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 5, 550, fill=color, outline="")
        canvas.create_oval(17, 18, 63, 64, fill="#e2bd6f", outline="#ffedac", width=2)
        canvas.create_oval(21, 22, 59, 60, fill="#fff1cc", outline="#725725")
        for x,y,col in ((40,29,"#cd798c"),(31,35,"#dcca70"),(49,35,"#78b078"),(31,46,"#858bd1"),
                        (49,46,"#c695c3"),(40,52,"#dea077")):
            canvas.create_oval(x-6,y-6,x+6,y+6,fill=col,outline="#fff1cc",width=1)
        y = 10
        for value, font, fg in ((title, ("Segoe UI",10,"bold"), color), (item, ("Segoe UI",15,"bold"), "#fffdf1"),
                                (detail, ("Segoe UI",10), "#e2e8e4")):
            line = canvas.create_text(76,y,text=value,fill=fg,font=font,anchor="nw",width=width-94)
            y = canvas.bbox(line)[3]+3
        return max(80,y+6)
    def tick():
        nonlocal current, remaining, stamp, last_width
        now = time.monotonic()
        while not inbox.empty():
            msg = inbox.get_nowait()
            if msg is None:
                root.destroy()
                return
            pending.append(msg)
        target = foreground()
        process = w.DWORD()
        if target:
            getpid(target, c.byref(process))
        bounds, point = w.RECT(), w.POINT(0, 0)
        active = (process.value == pid and rect(target,c.byref(bounds)) and bounds.right >= 200
                  and bounds.bottom >= 100 and screen(target,c.byref(point)))
        if active and current:
            remaining -= min(.25, now-stamp)
            if remaining <= 0:
                current = None
        stamp = now
        if active and not current and pending:
            current, remaining, last_width = pending.popleft(), 5., None
        if active and current:
            width = min(470,bounds.right-24)
            if width != last_width:
                tick.height = draw(current,width)
                last_width = width
            position(hwnd, c.c_void_p(-1), point.x+bounds.right-width-14, point.y+18, width, tick.height, 0x0050)
        else:
            show(hwnd, 0)
        root.after(100,tick)
    root.after(0,tick)
    root.mainloop()
