"""Desktop GUI control panel (Tkinter): `intake gui` / the bundled app.

Goal: a non-technical user never needs a terminal. The window provides:
- a Start/Stop toggle (the "manual run" style),
- live status + a recent-activity feed,
- buttons to open the inbox / review / repo / logs,
- a Settings dialog to pick the repo folder and paste the API key,
- "Run at login" and "Hide to tray" toggles.

Tkinter is used because it is in the Python standard library and bundles cleanly
into PyInstaller apps on Windows, macOS, and Linux. The IntakeService runs on its
own threads; the UI polls it (no cross-thread Tk calls).
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_DISPLAY_NAME, __version__, autostart
from .config import (
    Config,
    DEFAULT_MODEL,
    config_exists,
    load_config,
    resolve_api_key,
    save_config,
    store_api_key,
)
from .logging_setup import get_logger, recent_events
from .platform_utils import open_path, log_dir
from .singleton import SingleInstance

_DOT = {"watching": "#2ecc71", "paused": "#f1c40f", "stopped": "#95a5a6", "setup": "#e74c3c"}


class IntakeGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.log = get_logger(console=False)
        self.service = None  # type: ignore[assignment]
        self._tray = None

        root.title(APP_DISPLAY_NAME)
        root.minsize(560, 460)
        try:
            root.iconphoto(True, self._app_icon())
        except Exception:
            pass

        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh()  # kick off the periodic poll

        if not self._is_configured():
            self.root.after(300, lambda: self.open_settings(first_run=True))

    # --------------------------------------------------------------- UI build
    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        self.dot = tk.Canvas(top, width=16, height=16, highlightthickness=0)
        self.dot.pack(side="left")
        self._dot_id = self.dot.create_oval(2, 2, 14, 14, fill=_DOT["stopped"], outline="")
        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(top, textvariable=self.status_var, font=("", 11, "bold")).pack(side="left", padx=8)

        self.start_btn = ttk.Button(top, text="Start", command=self.toggle_start, width=12)
        self.start_btn.pack(side="right")

        # paths line
        self.paths_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.paths_var, foreground="#666").pack(fill="x", padx=12)

        # action buttons
        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Open inbox", command=lambda: self._open(self._cfg_path("intake"))).pack(side="left")
        ttk.Button(actions, text="Open review", command=lambda: self._open(self._cfg_path("review"))).pack(side="left", padx=6)
        ttk.Button(actions, text="Open repo", command=lambda: self._open(self._cfg_path("repo"))).pack(side="left")
        ttk.Button(actions, text="View log", command=lambda: open_path(log_dir())).pack(side="left", padx=6)
        ttk.Button(actions, text="Settings", command=self.open_settings).pack(side="right")

        # toggles
        toggles = ttk.Frame(self.root)
        toggles.pack(fill="x", **pad)
        self.autostart_var = tk.BooleanVar(value=autostart.status_path() is not None)
        ttk.Checkbutton(toggles, text="Run at login", variable=self.autostart_var,
                        command=self._toggle_autostart).pack(side="left")
        ttk.Button(toggles, text="Hide to tray", command=self.hide_to_tray).pack(side="right")

        # activity feed
        ttk.Label(self.root, text="Recent activity").pack(anchor="w", padx=12, pady=(8, 0))
        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.activity = tk.Text(frame, height=10, wrap="word", state="disabled",
                                background="#1e1e1e", foreground="#d4d4d4", relief="flat")
        scroll = ttk.Scrollbar(frame, command=self.activity.yview)
        self.activity.configure(yscrollcommand=scroll.set)
        self.activity.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        ttk.Label(self.root, text=f"{APP_DISPLAY_NAME} {__version__}", foreground="#999").pack(side="bottom", pady=4)

    # ------------------------------------------------------------- start/stop
    def toggle_start(self) -> None:
        if self.service and self.service.running:
            self.stop_service()
        else:
            self.start_service()

    def start_service(self) -> None:
        if not self._is_configured():
            self.open_settings(first_run=True)
            return
        from .watcher import IntakeService
        cfg = load_config()
        key = resolve_api_key(cfg)
        try:
            self.service = IntakeService(cfg, key, logger=self.log)
            self.service.start()
        except Exception as e:
            messagebox.showerror(APP_DISPLAY_NAME, f"Could not start:\n{e}")
            self.service = None
            return
        self._append(f"Started. Watching {cfg.intake_path}")

    def stop_service(self) -> None:
        if self.service:
            self.service.stop()
            self.service = None
            self._append("Stopped.")

    # ---------------------------------------------------------------- tray
    def hide_to_tray(self) -> None:
        try:
            import pystray

            from .trayicon import make_icon

            def show(icon, item):
                icon.stop()
                self._tray = None
                self.root.after(0, self.root.deiconify)

            def quit_all(icon, item):
                icon.stop()
                self._tray = None
                self.root.after(0, self._on_close)

            menu = pystray.Menu(
                pystray.MenuItem("Show window", show, default=True),
                pystray.MenuItem("Quit", quit_all),
            )
            self._tray = pystray.Icon("intake-agent", make_icon("watching" if self._running() else "stopped"),
                                      APP_DISPLAY_NAME, menu)
            self._tray.run_detached()
            self.root.withdraw()
        except Exception as e:
            # Tray not supported here; just minimise instead.
            self._append(f"(tray unavailable: {e}; minimising)")
            self.root.iconify()

    # -------------------------------------------------------------- settings
    def open_settings(self, first_run: bool = False) -> None:
        SettingsDialog(self.root, on_saved=self._after_settings_saved, first_run=first_run)

    def _after_settings_saved(self) -> None:
        self._append("Settings saved.")
        self._refresh_paths()

    # ------------------------------------------------------------ periodic UI
    def _refresh(self) -> None:
        self._refresh_paths()
        running = self._running()
        if self.service and self.service.paused:
            state = "paused"
        elif running:
            state = "watching"
        elif not self._is_configured():
            state = "setup"
        else:
            state = "stopped"

        labels = {"watching": "Watching", "paused": "Paused", "stopped": "Stopped",
                  "setup": "Needs setup"}
        text = labels[state]
        if running and self.service:
            s = self.service.stats()
            today = s.get("today", {})
            if today:
                text += "   (today: " + ", ".join(f"{k.lower()} {v}" for k, v in today.items()) + ")"
            if s.get("queued"):
                text += f"   [{s['queued']} queued]"
        self.status_var.set(text)
        self.dot.itemconfig(self._dot_id, fill=_DOT[state])
        self.start_btn.config(text="Stop" if running else "Start")

        self._sync_activity()
        self.root.after(1000, self._refresh)

    def _sync_activity(self) -> None:
        lines = recent_events(200)
        current = self.activity.get("1.0", "end-1c").count("\n") + 1 if self.activity.get("1.0", "end-1c") else 0
        if len(lines) != current:
            self.activity.config(state="normal")
            self.activity.delete("1.0", "end")
            self.activity.insert("1.0", "\n".join(lines))
            self.activity.see("end")
            self.activity.config(state="disabled")

    def _append(self, msg: str) -> None:
        self.log.info(msg)

    # ---------------------------------------------------------------- helpers
    def _running(self) -> bool:
        return bool(self.service and self.service.running)

    def _is_configured(self) -> bool:
        if not config_exists():
            return False
        try:
            cfg = load_config()
        except Exception:
            return False
        return not cfg.validate() and bool(resolve_api_key(cfg))

    def _cfg_path(self, which: str) -> Path | None:
        if not config_exists():
            return None
        cfg = load_config()
        return {"intake": cfg.intake_path, "review": cfg.review_path, "repo": cfg.repo_path}[which]

    def _open(self, path: Path | None) -> None:
        if path:
            open_path(path)

    def _refresh_paths(self) -> None:
        if config_exists():
            try:
                cfg = load_config()
                self.paths_var.set(f"{cfg.intake_path}  ->  {cfg.repo_path}")
                return
            except Exception:
                pass
        self.paths_var.set("Not configured - click Settings.")

    def _toggle_autostart(self) -> None:
        try:
            if self.autostart_var.get():
                autostart.enable()
                self._append("Enabled run at login.")
            else:
                autostart.disable()
                self._append("Disabled run at login.")
        except Exception as e:
            messagebox.showwarning(APP_DISPLAY_NAME, f"Could not change autostart:\n{e}")
            self.autostart_var.set(autostart.status_path() is not None)

    def _on_close(self) -> None:
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.stop_service()
        self.root.destroy()

    def _app_icon(self) -> tk.PhotoImage:
        from io import BytesIO

        from PIL import Image, ImageTk

        from .trayicon import make_icon
        img = make_icon("watching", 64)
        bio = BytesIO()
        img.save(bio, format="PNG")
        return ImageTk.PhotoImage(Image.open(bio))


# --------------------------------------------------------------------- settings
class SettingsDialog:
    def __init__(self, parent, on_saved, first_run: bool = False):
        self.on_saved = on_saved
        self.cfg = load_config() if config_exists() else Config()
        self.win = tk.Toplevel(parent)
        self.win.title("Intake Agent - Settings")
        self.win.transient(parent)
        self.win.grab_set()
        self.win.resizable(False, False)

        f = ttk.Frame(self.win, padding=16)
        f.pack(fill="both", expand=True)
        if first_run:
            ttk.Label(f, text="Welcome! Tell Intake Agent where to file documents.",
                      font=("", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.repo_var = tk.StringVar(value=self.cfg.repo_root)
        self.intake_var = tk.StringVar(value=self.cfg.intake_dir or "00_intake")
        self.policy_var = tk.StringVar(value=self.cfg.new_folder_policy or "prompt")
        self.model_var = tk.StringVar(value=self.cfg.model or DEFAULT_MODEL)
        self.key_var = tk.StringVar(value="")
        self.show_key = tk.BooleanVar(value=False)

        r = 1
        ttk.Label(f, text="Repository folder").grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.repo_var, width=44).grid(row=r, column=1, sticky="we")
        ttk.Button(f, text="Browse…", command=self._browse_repo).grid(row=r, column=2, padx=4)
        r += 1
        ttk.Label(f, text="Inbox folder").grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.intake_var, width=44).grid(row=r, column=1, sticky="we")
        ttk.Label(f, text="(in repo, or absolute)").grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Label(f, text="New-folder policy").grid(row=r, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.policy_var, values=["prompt", "auto", "review"],
                     state="readonly", width=12).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Model").grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.model_var, width=30).grid(row=r, column=1, sticky="w")
        r += 1
        existing = resolve_api_key(self.cfg) if config_exists() else ""
        hint = "(leave blank to keep current key)" if existing else "(starts with sk-ant-)"
        ttk.Label(f, text="Anthropic API key").grid(row=r, column=0, sticky="w")
        self.key_entry = ttk.Entry(f, textvariable=self.key_var, width=44, show="")
        self.key_entry.grid(row=r, column=1, sticky="we")
        ttk.Label(f, text=hint).grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="Show key", variable=self.show_key,
                        command=self._toggle_show).grid(row=r, column=1, sticky="w")
        r += 1
        self.status = ttk.Label(f, text="", foreground="#666")
        self.status.grid(row=r, column=0, columnspan=3, sticky="w", pady=(8, 4))
        r += 1
        btns = ttk.Frame(f)
        btns.grid(row=r, column=0, columnspan=3, sticky="e")
        ttk.Button(btns, text="Cancel", command=self.win.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="right")
        f.columnconfigure(1, weight=1)

    def _browse_repo(self) -> None:
        chosen = filedialog.askdirectory(title="Select your repository folder")
        if chosen:
            self.repo_var.set(chosen)

    def _toggle_show(self) -> None:
        self.key_entry.config(show="" if self.show_key.get() else "*")

    def _save(self) -> None:
        repo = Path(self.repo_var.get()).expanduser()
        if not repo.is_dir():
            messagebox.showerror("Settings", f"Repository folder does not exist:\n{repo}")
            return
        self.cfg.repo_root = str(repo)
        self.cfg.intake_dir = self.intake_var.get().strip() or "00_intake"
        self.cfg.new_folder_policy = self.policy_var.get()
        self.cfg.model = self.model_var.get().strip() or DEFAULT_MODEL
        self.cfg.intake_path.mkdir(parents=True, exist_ok=True)
        self.cfg.review_path.mkdir(parents=True, exist_ok=True)

        new_key = self.key_var.get().strip()
        if new_key:
            backend = store_api_key(new_key)
            if backend != "keychain":
                self.cfg.api_key_inline = new_key
        save_config(self.cfg)

        key = resolve_api_key(self.cfg)
        if not key:
            messagebox.showwarning("Settings", "Saved, but no API key is set yet.")
        else:
            self.status.config(text="Checking API key…")
            self.win.update_idletasks()
            ok, detail = _ping(self.cfg, key)
            if not ok:
                messagebox.showwarning("Settings", f"Saved, but the API check failed:\n{detail}")
        self.on_saved()
        self.win.destroy()


def _ping(cfg: Config, key: str) -> tuple[bool, str]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key, timeout=20, max_retries=0)
        client.messages.create(model=cfg.model, max_tokens=1, messages=[{"role": "user", "content": "hi"}])
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def run_gui() -> int:
    guard = SingleInstance()
    if not guard.acquire():
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo(APP_DISPLAY_NAME, f"{APP_DISPLAY_NAME} is already running.")
        root.destroy()
        return 0
    try:
        root = tk.Tk()
        IntakeGUI(root)
        root.mainloop()
        return 0
    finally:
        guard.release()


def main() -> int:
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
