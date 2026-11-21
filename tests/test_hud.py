import ctypes, io, json, sys, time
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path('dist/Client-OOT-Remake.pyz').resolve()))
from ootrr_triforce.hud import overlay

# Exercise the shipped event loop, Win32 calls and Tk draw arguments, with simulated windows.
class Pipe:
    def __iter__(self):
        yield json.dumps(["Objet reçu via Archipelago", "Mirror Shield", "De Ami", "in"]).encode()
        while not done[0]:time.sleep(.004)

class Op:
    def __init__(self, fn):self.fn=fn
    def __call__(self,*args):return self.fn(*args)

class Win:
    foreground=101
    def __init__(self):
        self.GetForegroundWindow=Op(lambda:self.foreground)
        self.GetWindowThreadProcessId=Op(lambda hwnd,p:setattr(p._obj,'value',44 if hwnd==101 else 55) or 1)
        def getrect(win,p):
            p._obj.right,p._obj.bottom=900,600
            return 1
        def toscreen(win,p):
            p._obj.x,p._obj.y=-885,21
            return 1
        self.GetClientRect=Op(getrect);self.ClientToScreen=Op(toscreen)
        self.SetProcessDpiAwarenessContext=Op(lambda ctx:1)
        self.GetAncestor=Op(lambda *args:12);self.GetWindowLongW=Op(lambda *args:0)
        self.SetWindowLongW=Op(lambda *args:styles.append(args[-1]))
        self.SetWindowPos=Op(lambda *args:positions.append(args))
        self.ShowWindow=Op(lambda hwnd,which:shown.append(which))

class Window:
    def __getattr__(self,k):return lambda *args:None
    def winfo_id(self):return 11
    def after(self,ms,cb):self.tick=cb
    def mainloop(self):
        for _ in range(100):
            self.tick()
            if positions:break
            time.sleep(.003)
        assert any(t=='Mirror Shield' for t in strings) and 'De Ami' in strings
        assert positions[-1][2:4]==(-469,39) and positions[-1][-1] & 0x10
        assert styles[-1] & 0x08000020==0x08000020
        previous=len(positions)
        win.foreground=111;self.tick()
        assert len(positions)==previous and shown[-1]==0
        win.foreground=101;self.tick();assert len(positions)==previous+1
        done[0]=True
class Canvas:
    def __init__(self,*args,**kw):pass
    def __getattr__(self,k):return lambda *args,**kwargs:None
    def create_text(self,x,y,**kw):strings.append(kw['text']);return y
    def bbox(self,y):return (76,y,205,y+20)

strings=[];positions=[];styles=[];shown=[];done=[False];win=Win()
with patch.object(ctypes,'WinDLL',return_value=win,create=True),patch('tkinter.Tk',Window),patch('tkinter.Canvas',Canvas),patch.object(sys,'stdin',SimpleNamespace(buffer=Pipe())):
    overlay(44)
print('PASS Windows HUD controller: real drawing path with simulated APIs, exact text, click-through/no-focus flags, negative monitor position, hides on Alt-Tab, resumes after refocus.')
