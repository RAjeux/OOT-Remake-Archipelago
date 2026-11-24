"""Named room selection and a passive, spoiler-safe Archipelago checklist."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .i18n import tr
from .room_library import LibraryError, room_progress


class RoomsWindow:
    def __init__(self, master, library, *, language="en", on_select=None, on_backup=None):
        self.master, self.library, self.language = master, library, language
        self.on_select, self.on_backup = on_select, on_backup
        self.closed, self.records = False, {}
        master.title(self.text("My rooms"))
        master.geometry("850x480")
        master.minsize(650, 350)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(1, weight=1)
        ttk.Label(master, text=self.text("Each room keeps its own saves and history. Close Zelda before changing rooms."),
                  wraplength=790, padding=16).grid(row=0, column=0, sticky="ew")
        area = ttk.Frame(master, padding=(16, 0))
        area.grid(row=1, column=0, sticky="nsew")
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.list = ttk.Treeview(area, columns=("host", "slot", "room"), selectmode="browse")
        self.list.heading("#0", text=self.text("Name"))
        for column, label in (("host", "Game host"), ("slot", "Player"), ("room", "Room")):
            self.list.heading(column, text=self.text(label))
        self.list.column("#0", width=260)
        self.list.column("host", width=90, stretch=False)
        self.list.column("slot", width=120, stretch=False)
        self.list.column("room", width=190)
        self.list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self.list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.list.configure(yscrollcommand=scrollbar.set)
        self.list.bind("<Double-1>", lambda _event: self.select())
        actions = ttk.Frame(master, padding=16)
        actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(actions, text=self.text("Refresh"), command=self.refresh).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self.text("Rename…"), command=self.rename).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text=self.text("Back up saves"), command=self.backup).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text=self.text("Use this room"), command=self.select).grid(row=0, column=3)
        self.status = ttk.Label(master, padding=(16, 0, 16, 14), wraplength=790)
        self.status.grid(row=3, column=0, sticky="ew")
        master.protocol("WM_DELETE_WINDOW", self.close)
        master.bind("<Escape>", lambda _event: self.close())
        self.refresh()

    def text(self, message, **values):
        return tr(message, language=self.language, **values)

    def refresh(self):
        selection = self.list.selection()
        self.list.delete(*self.list.get_children())
        self.records = {row["key"]: row for row in self.library.rooms()}
        for key, row in self.records.items():
            self.list.insert("", "end", iid=key, text=row["name"], values=(row["host"], row["slot"], row["room"]))
        if selection and selection[0] in self.records:
            self.list.selection_set(selection)
        self.status.configure(text="" if self.records else self.text("No prepared rooms yet. Set up a room first."))

    def selected(self):
        selected = self.list.selection()
        return self.records.get(selected[0]) if selected else None

    def select(self):
        row = self.selected()
        if row and self.on_select:
            self.on_select(row["key"])

    def backup(self):
        row = self.selected()
        if row and self.on_backup:
            self.on_backup(row["key"])

    def rename(self):
        row = self.selected()
        if not row:
            return
        name = simpledialog.askstring(self.text("Rename room"), self.text("Room name"),
                                      initialvalue=row["name"], parent=self.master)
        if name is not None:
            try:
                self.library.rename(row["key"], name)
            except (LibraryError, OSError) as error:
                self.status.configure(text=self.text(str(error)))
                return
            self.refresh()

    def close(self):
        if not self.closed:
            self.closed = True
            self.master.destroy()


class ProgressWindow:
    def __init__(self, master, profile, *, artifact=None, language="en", provider_factory=None, save_selection=True):
        self.master, self.profile, self.language = master, Path(profile), language
        self.closed, self.after, self.rows = False, None, []
        self.inventory_rows, self.key_rows, self.soul_rows, self.save_paths = [], [], [], []
        self.jobs, self.results = queue.Queue(maxsize=1), queue.Queue()
        self.stop = threading.Event()
        self.pending = False
        if provider_factory is None:
            from .tracker_service import ProfileTracker
            provider_factory = ProfileTracker
        master.title(self.text("Archipelago tracker"))
        master.geometry("850x560")
        master.minsize(650, 380)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(2, weight=1)
        self.summary = ttk.Label(master, padding=16, font=("Segoe UI", 12, "bold"))
        self.summary.grid(row=0, column=0, sticky="ew")
        filters = ttk.Frame(master, padding=(16, 0, 16, 12))
        filters.grid(row=1, column=0, sticky="ew")
        filters.columnconfigure(1, weight=1)
        save_label = ttk.Label(filters, text=self.text("Save"))
        save_label.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.save_choice = ttk.Combobox(filters, state="readonly")
        self.save_choice.grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 10))
        self.save_choice.bind("<<ComboboxSelected>>", lambda _event: self.request())
        if not save_selection:
            save_label.grid_remove()
            self.save_choice.grid_remove()
        ttk.Label(filters, text=self.text("Search")).grid(row=1, column=0, padx=(0, 8))
        self.search = tk.StringVar()
        ttk.Entry(filters, textvariable=self.search).grid(row=1, column=1, sticky="ew")
        self.hide_completed = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text=self.text("Hide completed"), variable=self.hide_completed,
                        command=self.render).grid(row=1, column=2, padx=(12, 0))
        self.access_filter = ttk.Combobox(filters, state="readonly", width=15,
            values=tuple(self.text(label) for label in ("All locations", "Available", "Blocked", "Unknown")))
        self.access_filter.current(0)
        self.access_filter.grid(row=1, column=3, padx=(12, 0))
        self.access_filter.bind("<<ComboboxSelected>>", lambda _event: self.render())
        self.search.trace_add("write", lambda *_args: self.render())
        notebook = ttk.Notebook(master)
        notebook.grid(row=2, column=0, sticky="nsew", padx=16)
        area = ttk.Frame(notebook)
        notebook.add(area, text=self.text("Checks"))
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.list = ttk.Treeview(area, columns=("status", "access"), selectmode="browse")
        self.list.heading("#0", text=self.text("Location"))
        self.list.heading("status", text=self.text("Status"))
        self.list.heading("access", text=self.text("Access"))
        self.list.column("#0", width=480)
        self.list.column("status", width=130, stretch=False)
        self.list.column("access", width=130, stretch=False)
        self.list.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self.list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.list.configure(yscrollcommand=scrollbar.set)
        self.inventory = self._table(notebook, "Inventory", (("count", "Amount"),))
        self.keys = self._table(notebook, "Dungeon keys", (("small", "Small keys"), ("boss", "Boss key")))
        self.souls = self._table(notebook, "Enemy souls", (("owned", "Status"),))
        self.detail = ttk.Label(master, wraplength=790, padding=(16, 12, 16, 0))
        self.detail.grid(row=3, column=0, sticky="ew")
        ttk.Label(master, text=self.text("Checks come from the game's committed Archipelago history. Uncollected rewards stay hidden."),
                  wraplength=790, padding=16).grid(row=4, column=0, sticky="ew")
        master.protocol("WM_DELETE_WINDOW", self.close)
        master.bind("<Escape>", lambda _event: self.close())
        profile_path, stop_event, jobs, results = self.profile, self.stop, self.jobs, self.results
        def work():
            try:
                provider = provider_factory(profile_path, artifact)
            except Exception:
                provider = None
            while not stop_event.is_set():
                try:
                    path = jobs.get(timeout=.2)
                except queue.Empty:
                    continue
                try:
                    if provider is None:
                        raise ValueError()
                    result = provider.refresh(path)
                except Exception:
                    result = room_progress(profile_path)
                    result.update(inventory=[], keys=[], souls=[], saves=[], tracking_status="The selected save is unavailable. The last valid inventory is kept.")
                results.put(result)
        self.worker = threading.Thread(target=work, name="Archipelago save tracker", daemon=True)
        self.worker.start()
        self.request()
        self.after = self.master.after(100, self.receive)

    def text(self, message, **values):
        return tr(message, language=self.language, **values)

    def _table(self, notebook, title, columns):
        pane = ttk.Frame(notebook)
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        table = ttk.Treeview(pane, columns=tuple(key for key, _label in columns))
        table.heading("#0", text=self.text("Name"))
        for key, label in columns:
            table.heading(key, text=self.text(label))
            table.column(key, width=150, stretch=False)
        table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(pane, orient="vertical", command=table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        table.configure(yscrollcommand=scroll.set)
        notebook.add(pane, text=self.text(title))
        return table

    def request(self):
        if self.closed or self.pending:
            return
        selected = self.save_choice.current()
        path = self.save_paths[selected] if 0 <= selected < len(self.save_paths) else ""
        try:
            self.jobs.put_nowait(path)
            self.pending = True
        except queue.Full:
            pass

    def receive(self):
        if self.closed:
            return
        while True:
            try:
                snapshot = self.results.get_nowait()
            except queue.Empty:
                break
            self.pending = False
            selected = self.save_choice.current()
            current = self.save_paths[selected] if 0 <= selected < len(self.save_paths) else ""
            self.save_paths = snapshot.get("saves", [])
            self.save_choice.configure(values=tuple(str(Path(path).relative_to(self.profile / "user/save")) for path in self.save_paths))
            if current in self.save_paths:
                self.save_choice.current(self.save_paths.index(current))
            elif len(self.save_paths) == 1:
                self.save_choice.current(0)
            else:
                self.save_choice.set("")
            self.rows = snapshot["locations"]
            self.inventory_rows = snapshot.get("inventory", [])
            self.key_rows, self.soul_rows = snapshot.get("keys", []), snapshot.get("souls", [])
            self.summary.configure(text=self.text("{slot} · {checked}/{total} checks completed", **snapshot))
            self.detail.configure(text=self.text(snapshot.get("tracking_status", "")))
            self.render()
        self.request()
        self.after = self.master.after(1000, self.receive)

    def render(self):
        query = self.search.get().strip().casefold()
        selection = self.list.selection()
        self.list.delete(*self.list.get_children())
        access_filter = (None, "available", "blocked", "unknown")[max(0, self.access_filter.current())]
        for row in sorted(self.rows, key=lambda item: item["name"].casefold()):
            if (query and query not in row["name"].casefold()) or (self.hide_completed.get() and row["checked"]):
                continue
            if access_filter and row.get("access", "unknown") != access_filter:
                continue
            self.list.insert("", "end", iid=str(row["id"]), text=row["name"],
                             values=(self.text("Completed" if row["checked"] else "Not completed"),
                                     self.text({"available": "Available", "blocked": "Blocked", "partial": "Partial"}.get(row.get("access"), "Unknown"))))
        if selection and self.list.exists(selection[0]):
            self.list.selection_set(selection)
        from .item_names import item_name
        self.inventory.delete(*self.inventory.get_children())
        for row in self.inventory_rows:
            self.inventory.insert("", "end", text=item_name(row["name"], self.language),
                                  values=(row["count"] if row["known"] else self.text("Unknown"),))
        self.keys.delete(*self.keys.get_children())
        for dungeon, small, boss in self.key_rows:
            self.keys.insert("", "end", text=dungeon,
                             values=(f"{small[0]}/{small[1]}" if small is not None else self.text("Unknown"),
                                     self.text("Owned" if boss else "Not owned") if boss is not None else self.text("Unknown")))
        self.souls.delete(*self.souls.get_children())
        for zone, souls in self.soul_rows:
            parent = self.souls.insert("", "end", text=zone, open=True)
            for name, owned in souls:
                self.souls.insert(parent, "end", text=name, values=(self.text("Owned" if owned else "Not owned"),))

    def close(self):
        if not self.closed:
            self.closed = True
            self.stop.set()
            if self.after:
                self.master.after_cancel(self.after)
            self.master.destroy()
