"""Compact dark control surface and a separate pinnable quick-type pill."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .engine import Engine
from .models import install
from .transcribe import MODEL_NAMES

BG = "#0e1117"
SURFACE = "#171c25"
RAISED = "#202735"
EDGE = "#303a49"
TEXT = "#eff3fb"
MUTED = "#9aa8bb"
ACCENT = "#a1f0c3"
RED = "#ff928e"
FONT = "Segoe UI"


class App:
    def __init__(self, engine: Engine, close_app):
        self.engine = engine
        self.close_app = close_app
        self.root = tk.Tk()
        self.root.title("5imic — the borrowed voice instrument")
        self.root.geometry("880x660")
        self.root.minsize(760, 600)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._icon(self.root)
        self.error = tk.StringVar(value="Preparing audio engine…")
        self.progress = tk.StringVar(value="Ready to listen when you are.")
        self.input = tk.StringVar()
        self.mode = tk.StringVar(value=engine.settings.mode)
        self.effect = tk.StringVar(value=engine.settings.effect)
        self.model = tk.StringVar(value=engine.settings.model)
        self.source = tk.StringVar(value=engine.settings.capture_device)
        self._build()
        self._build_pill()
        self._refresh()
        threading.Thread(target=self.engine.start, daemon=True).start()
        self.root.after(1000, self.show_pill)

    @staticmethod
    def _icon(window):
        # Embedded tiny icon, so an installation never depends on a separate asset.
        pixels = ["#131921", "#a1f0c3", "#28384a"]
        icon = tk.PhotoImage(width=32, height=32, master=window)
        icon.put(pixels[0], to=(0, 0, 32, 32))
        icon.put(pixels[1], to=(7, 13, 11, 20))
        icon.put(pixels[1], to=(13, 8, 17, 24))
        icon.put(pixels[1], to=(19, 12, 23, 21))
        window.iconphoto(False, icon)
        window._fiveimic_icon = icon

    def label(self, parent, text, size=10, fg=MUTED, bold=False, **options):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=fg,
                        font=(FONT, size, "bold" if bold else "normal"), **options)

    def button(self, parent, text, callback, primary=False, width=None):
        return tk.Button(parent, text=text, command=callback,
                         font=(FONT, 10, "bold"), fg=BG if primary else TEXT,
                         bg=ACCENT if primary else RAISED, activebackground="#c9ffde",
                         activeforeground=BG, relief="flat", cursor="hand2",
                         padx=14, pady=10, width=width)

    def _build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 10))
        self.label(header, "5", 26, ACCENT, True).pack(side="left")
        self.label(header, "IMIC", 23, TEXT, True).pack(side="left", padx=(2, 16))
        self.label(header, "BORROWED VOICE STUDIO  /  LOCAL-FIRST", 9).pack(side="left")
        self.button(header, "Open pill ↗", self.show_pill).pack(side="right")

        line = tk.Frame(self.root, height=1, bg=EDGE)
        line.pack(fill="x", padx=28, pady=8)
        metrics = tk.Frame(self.root, bg=BG)
        metrics.pack(fill="x", padx=28, pady=(10, 18))
        self.metric_widgets = {}
        for key, title in (("clips", "CLIPS"), ("phrases", "PHRASES"),
                           ("used", "DISK USED"), ("asr", "LAST ASR")):
            card = tk.Frame(metrics, bg=SURFACE, padx=18, pady=13)
            card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            self.label(card, title, 9).pack(anchor="w")
            widget = self.label(card, "—", 20, TEXT, True)
            widget.pack(anchor="w", pady=(5, 0))
            self.metric_widgets[key] = widget

        entry_card = tk.Frame(self.root, bg=SURFACE, padx=20, pady=18)
        entry_card.pack(fill="x", padx=28)
        heading = tk.Frame(entry_card, bg=SURFACE)
        heading.pack(fill="x")
        self.label(heading, "SAY SOMETHING", 10, ACCENT, True).pack(side="left")
        self.label(heading, "Only words collected from real audio", 9).pack(side="right")
        input_row = tk.Frame(entry_card, bg=SURFACE)
        input_row.pack(fill="x", pady=(14, 4))
        input_box = tk.Entry(input_row, textvariable=self.input, bg=RAISED, fg=TEXT,
                             insertbackground=ACCENT, font=(FONT, 15), relief="flat",
                             highlightthickness=1, highlightbackground=EDGE,
                             highlightcolor=ACCENT)
        input_box.pack(side="left", fill="x", expand=True, ipady=11)
        input_box.bind("<Return>", lambda _: self.speak())
        self.button(input_row, "Speak  ↗", self.speak, primary=True).pack(side="right", padx=(12, 0))

        controls = tk.Frame(self.root, bg=BG)
        controls.pack(fill="x", padx=28, pady=(18, 6))
        self.record_btn = self.button(controls, "●  Start recording", self.toggle, primary=True)
        self.record_btn.pack(side="left")
        puppet = self.button(controls, "Hold to talk", lambda: None)
        puppet.pack(side="left", padx=(10, 0))
        puppet.bind("<ButtonPress-1>", lambda _: self.engine.puppet_start())
        puppet.bind("<ButtonRelease-1>", lambda _: self.engine.puppet_stop())
        self.button(controls, "Check audio", self.check_audio).pack(side="left", padx=10)
        self.button(controls, "Download model", self.install_model).pack(side="left")
        self.button(controls, "Clip library", self.show_clips).pack(side="left", padx=10)

        source_row = tk.Frame(self.root, bg=BG)
        source_row.pack(fill="x", padx=28, pady=(8, 0))
        self.label(source_row, "CAPTURE OUTPUT", 9).pack(side="left", padx=(0, 12))
        try:
            from .audio import list_devices
            source_names = ["default", *list_devices()["speakers"]]
        except Exception:
            source_names = ["default"]
        source_picker = ttk.Combobox(source_row, values=source_names,
                                    textvariable=self.source, state="readonly",
                                    style="Five.TCombobox", width=40)
        source_picker.pack(side="left", fill="x", expand=True)
        source_picker.bind("<<ComboboxSelected>>", self.set_source)
        self.label(source_row, "CONF ≥", 9).pack(side="left", padx=(20, 6))
        confidence = tk.Scale(source_row, from_=0.4, to=0.95, resolution=0.05,
                              orient="horizontal", showvalue=True, length=150,
                              bg=BG, fg=TEXT, troughcolor=RAISED, highlightthickness=0,
                              activebackground=ACCENT, bd=0,
                              command=self.set_confidence)
        confidence.set(self.engine.settings.confidence)
        confidence.pack(side="left")

        selectors = tk.Frame(self.root, bg=BG)
        selectors.pack(fill="x", padx=28, pady=(14, 8))
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Five.TCombobox", fieldbackground=RAISED, background=RAISED,
                        foreground=TEXT, arrowcolor=ACCENT, bordercolor=EDGE,
                        lightcolor=EDGE, darkcolor=EDGE, padding=6)
        for i, (label, var, options) in enumerate((
            ("VOICE MODE", self.mode, ("natural", "low", "high", "chaos")),
            ("AUDIO FX", self.effect, ("clean", "crush", "glitch")),
            ("RECOGNIZER", self.model, MODEL_NAMES),
        )):
            slot = tk.Frame(selectors, bg=BG)
            slot.pack(side="left", fill="x", expand=True, padx=(0, 20) if i < 2 else 0)
            self.label(slot, label, 9).pack(anchor="w", pady=(0, 5))
            chooser = ttk.Combobox(slot, values=options, textvariable=var,
                                   state="readonly", style="Five.TCombobox")
            chooser.pack(fill="x")
            chooser.bind("<<ComboboxSelected>>", self.set_options)

        info = tk.Frame(self.root, bg=BG)
        info.pack(fill="x", padx=28, pady=(16, 4))
        self.label(info, "LIVE SESSION", 9, ACCENT, True).pack(anchor="w")
        self.status_label = self.label(info, "Waiting for audio…", 11, TEXT)
        self.status_label.pack(anchor="w", pady=(6, 2))
        self.transcript_label = self.label(info, "Transcript preview appears here", 9)
        self.transcript_label.pack(anchor="w")
        self.progress_label = self.label(info, "", 9, ACCENT, wraplength=785, justify="left")
        self.progress_label.pack(anchor="w", pady=(4, 0))
        self.error_label = self.label(info, "", 9, RED, wraplength=785, justify="left")
        self.error_label.pack(anchor="w", pady=(6, 0))
        self.label(self.root, "Private on-device storage  ·  200 MB default cap  ·  Recording is opt-in",
                   9).pack(side="bottom", anchor="w", padx=28, pady=16)

    def _build_pill(self):
        self.pill = tk.Toplevel(self.root)
        self.pill.title("5imic Quick Type")
        self.pill.overrideredirect(True)
        self.pill.attributes("-topmost", self.engine.settings.pinned)
        self.pill.geometry(f"480x70+{self.engine.settings.overlay_x}+{self.engine.settings.overlay_y}")
        self.pill.configure(bg=ACCENT)
        outer = tk.Frame(self.pill, bg=SURFACE, padx=12, pady=9)
        outer.pack(fill="both", expand=True, padx=2, pady=2)
        self.pill_status = self.label(outer, "●", 11, ACCENT, True)
        self.pill_status.pack(side="left")
        self.pill_status.configure(cursor="hand2")
        self.pill_status.bind("<Button-1>", lambda _: self.toggle())
        pill_entry = tk.Entry(outer, bg=SURFACE, fg=TEXT, insertbackground=ACCENT,
                             font=(FONT, 13), relief="flat", width=24)
        pill_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=5)
        pill_entry.insert(0, "Type and press Enter…")
        pill_entry.bind("<FocusIn>", lambda _: pill_entry.delete(0, "end") if
                        pill_entry.get() == "Type and press Enter…" else None)
        pill_entry.bind("<Return>", lambda _: self.speak(pill_entry.get()))
        self.button(outer, "↗", lambda: self.speak(pill_entry.get())).pack(side="left")
        self.pin_btn = self.button(outer, "◆", self.toggle_pin)
        self.pin_btn.pack(side="left", padx=4)
        self.button(outer, "□", self.root.deiconify).pack(side="left", padx=4)
        self.button(outer, "×", self.pill.withdraw).pack(side="left")
        self.pill_entry = pill_entry
        self.pill.bind("<ButtonPress-1>", self._drag_start)
        self.pill.bind("<B1-Motion>", self._drag)
        outer.bind("<ButtonPress-1>", self._drag_start)
        outer.bind("<B1-Motion>", self._drag)
        self.pill.withdraw()

    def _drag_start(self, event):
        self.drag_x, self.drag_y = event.x_root - self.pill.winfo_x(), event.y_root - self.pill.winfo_y()

    def _drag(self, event):
        x, y = event.x_root - self.drag_x, event.y_root - self.drag_y
        self.pill.geometry(f"+{x}+{y}")
        self.engine.settings.overlay_x, self.engine.settings.overlay_y = x, y

    def show_pill(self):
        self.pill.deiconify()
        self.pill.lift()
        self.pill_entry.focus_set()

    def toggle_pin(self):
        self.engine.settings.pinned = not self.engine.settings.pinned
        self.pill.attributes("-topmost", self.engine.settings.pinned)
        self.pin_btn.configure(text="◆" if self.engine.settings.pinned else "◇")

    def toggle(self):
        if not self.engine.running:
            self.error.set("Audio engine is still starting")
            return
        self.engine.toggle()

    def check_audio(self):
        status = self.engine.router.status
        messagebox.showinfo("5imic audio routing", status + "\n\nSelect '5imic Virtual Microphone' "
            "in the voice-chat app. The preview plays directly to your regular speakers. "
            "No loopbacks are made between desktop audio and the virtual microphone.")

    def set_options(self, _=None):
        try:
            self.engine.update(mode=self.mode.get(), effect=self.effect.get(),
                               model=self.model.get())
            self.error.set("")
        except Exception as exc:
            self.error.set(str(exc))

    def set_source(self, _=None):
        try:
            self.engine.set_capture_device(self.source.get())
            self.error.set("")
        except Exception as exc:
            self.error.set(str(exc))

    def set_confidence(self, value):
        self.engine.settings.confidence = float(value)
        self.engine.settings.save(self.engine.root)

    def install_model(self):
        self.progress.set("Downloading model…")
        def run():
            try:
                install(self.model.get(), self.engine.root,
                        lambda msg: self.root.after(0, self.progress.set, msg))
                self.root.after(0, self.error.set, "")
            except Exception as exc:
                self.root.after(0, self.error.set, str(exc))
        threading.Thread(target=run, daemon=True).start()

    def show_clips(self):
        window = tk.Toplevel(self.root)
        window.title("5imic · Clip Library")
        window.geometry("740x450")
        window.configure(bg=BG)
        self._icon(window)
        self.label(window, "RECORDED PHRASES", 15, ACCENT, True).pack(anchor="w",
            padx=20, pady=(18, 10))
        cols = ("id", "text", "confidence", "pitch", "pinned")
        style = ttk.Style()
        style.configure("Five.Treeview", background=SURFACE, foreground=TEXT,
                        fieldbackground=SURFACE, borderwidth=0, rowheight=28)
        style.configure("Five.Treeview.Heading", background=RAISED, foreground=TEXT)
        tree = ttk.Treeview(window, columns=cols, show="headings", style="Five.Treeview")
        for col, width in (("id", 55), ("text", 350), ("confidence", 100),
                           ("pitch", 75), ("pinned", 70)):
            tree.heading(col, text=col.upper())
            tree.column(col, width=width, stretch=(col == "text"))
        tree.pack(fill="both", expand=True, padx=20, pady=8)

        def populate():
            for item in tree.get_children():
                tree.delete(item)
            for item in self.engine.clips(200):
                tree.insert("", "end", values=(item["id"], item["text"],
                            item["confidence"], item["pitch"],
                            "YES" if item["pinned"] else "—"))

        def pin_selected():
            selection = tree.selection()
            if selection:
                ident = int(tree.item(selection[0], "values")[0])
                record = next((c for c in self.engine.arena.clips() if c.id == ident), None)
                if record:
                    self.engine.arena.pin(ident, not record.pinned)
                    populate()

        controls = tk.Frame(window, bg=BG)
        controls.pack(fill="x", padx=20, pady=(4, 18))
        self.button(controls, "Pin / unpin selected", pin_selected, primary=True).pack(side="left")
        self.button(controls, "Refresh", populate).pack(side="left", padx=8)
        self.label(controls, "Recent 200 clips · pinned phrases survive clear/eviction",
                   9).pack(side="right")
        populate()

    def speak(self, text=None):
        phrase = text if isinstance(text, str) else self.input.get()
        if not phrase.strip():
            return
        self.error.set("Assembling and playing…")
        def run():
            response = self.engine.say(phrase)
            if response["ok"]:
                message = (f"Played {response['spoken']}  ·  "
                           f"{round(response['coverage'] * 100)}% exact word coverage")
                self.root.after(0, self.error.set, "")
                self.root.after(0, self.progress.set, message)
            else:
                self.root.after(0, self.error.set, response["error"])
                if response.get("missing"):
                    self.root.after(0, self.progress.set,
                        "Missing: " + ", ".join(response["missing"]))
        threading.Thread(target=run, daemon=True).start()

    def _refresh(self):
        try:
            data = self.engine.stats()
            values = {"clips": str(data["clips"]), "phrases": str(data["phrases"]),
                      "used": f"{data['bytes']/1024/1024:.1f} MB",
                      "asr": f"{data['asr_ms']:.0f} ms"}
            for key, label in self.metric_widgets.items():
                label.configure(text=values[key])
            self.status_label.configure(text=data["status"][:100])
            self.transcript_label.configure(text=("Last heard: " + data["transcript"])[:120])
            self.progress_label.configure(text=self.progress.get()[:120])
            self.record_btn.configure(text="■  Pause recording" if data["recording"]
                                      else "●  Start recording")
            self.pill_status.configure(fg=RED if data["recording"] else ACCENT)
        except Exception:
            pass
        self.root.after(650, self._refresh)

    def close(self):
        self.engine.settings.save(self.engine.root)
        self.pill.destroy()
        self.root.destroy()
        self.close_app()

    def run(self):
        self.root.mainloop()
