#!/usr/bin/env python3
"""
Local Tempest WX
Local UDP display for WeatherFlow Tempest weather stations.
Cross-platform (Windows / macOS / Linux). Tray and autostart are optional.
"""

import socket
import json
import threading
import webbrowser
import sys
import os
import math
import platform
import tkinter as tk
from tkinter import ttk, colorchooser
from datetime import datetime, UTC
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    import ctypes
    from ctypes import wintypes
    HAS_CTYPES = IS_WINDOWS
except ImportError:
    HAS_CTYPES = False

UDP_PORT = 50222
BUFFER_SIZE = 4096
CONFIG_FILE = Path(__file__).with_name("tempest_display_config.json")

APP_NAME = "Local Tempest WX"
APP_VERSION = "1.4"
AUTHOR = "silicon"
AUTHOR_EMAIL = "silicon@orangedragon.co"
AUTHOR_URL = "https://orangedragon.co/labs/dev"

# ---------- Helpers ----------
def c_to_f(c): return c * 9 / 5 + 32
def f_to_c(f): return (f - 32) * 5 / 9
def mps_to_mph(mps): return mps * 2.23694
def mps_to_kmh(mps): return mps * 3.6
def mps_to_kts(mps): return mps * 1.94384
def mb_to_inhg(mb): return mb * 0.02953
def mb_to_mmhg(mb): return mb * 0.750062
def mm_to_inches(mm): return mm / 25.4

def degrees_to_compass(deg):
    if deg is None:
        return "—"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((deg + 11.25) / 22.5) % 16]

def dew_point_c(temp_c, rh):
    if temp_c is None or rh is None or rh <= 0:
        return None
    a, b = 17.27, 237.7
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(rh / 100.0)
    return (b * alpha) / (a - alpha)

def feels_like_c(temp_c, rh, wind_mps=None):
    if temp_c is None or rh is None:
        return None
    t_f = c_to_f(temp_c)
    if wind_mps is not None and t_f <= 50 and wind_mps >= 1.34:
        v = mps_to_mph(wind_mps)
        wc = 35.74 + 0.6215 * t_f - 35.75 * (v ** 0.16) + 0.4275 * t_f * (v ** 0.16)
        return f_to_c(wc)
    if t_f >= 80:
        hi = (-42.379 + 2.04901523 * t_f + 10.14333127 * rh
              - 0.22475541 * t_f * rh - 6.83783e-3 * t_f ** 2
              - 5.481717e-2 * rh ** 2 + 1.22874e-3 * t_f ** 2 * rh
              + 8.5282e-4 * t_f * rh ** 2 - 1.99e-6 * t_f ** 2 * rh ** 2)
        return f_to_c(hi)
    return temp_c

def apply_rounded_corners(hwnd, enable=True):
    """Windows 11 only. No-op elsewhere."""
    if not HAS_CTYPES:
        return
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        value = ctypes.c_int(DWMWCP_ROUND if enable else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass

def startup_shortcut_path():
    if not IS_WINDOWS:
        return None
    startup = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return startup / "Local Tempest WX.bat"

def set_autostart(enabled, script_path):
    """Windows only. Returns True on success or if not applicable."""
    if not IS_WINDOWS:
        return False
    link = startup_shortcut_path()
    if link is None:
        return False
    if enabled:
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
            content = (
                f'@echo off\r\n'
                f'cd /d "{script_path.parent}"\r\n'
                f'start "" pythonw "{script_path.name}"\r\n'
            )
            link.write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            print(f"Autostart enable failed: {e}")
            return False
    else:
        try:
            if link.exists():
                link.unlink()
            return True
        except Exception as e:
            print(f"Autostart disable failed: {e}")
            return False

def is_autostart_enabled():
    if not IS_WINDOWS:
        return False
    link = startup_shortcut_path()
    return link is not None and link.exists()

def make_tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=(30, 144, 255, 255))
    d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 220))
    return img

def play_alert():
    """Cross-platform best-effort sound."""
    if IS_WINDOWS and HAS_WINSOUND:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            winsound.Beep(880, 120)
        except Exception:
            pass
    else:
        # Fallback: terminal bell (works on many terminals / some systems)
        print("\a", end="", flush=True)

class TempestDisplay:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.script_path = Path(__file__).resolve()

        self.defaults = {
            "temp_unit": "F", "wind_unit": "mph", "baro_unit": "inHg", "rain_unit": "in",
            "always_on_top": False, "dark_mode": False,
            "font_size": 12, "temp_font_size": 28,
            "use_local_time": True, "time_24h": False,
            "geometry": "460x660", "compact_geometry": "320x150",
            "settings_geometry": "480x720", "compact_mode": False,
            "temp_color": "#111111", "humidity_color": "#333333",
            "rain_color": "#1e90ff",
            "minimize_to_tray": True,
            "lightning_alert": True,
            "autostart": False,
            "show_fields": {
                "pressure": True, "wind_avg": True, "wind_gust": True,
                "wind_lull": True, "wind_dir": True, "rapid_wind": True,
                "feels_like": True, "dew_point": True,
                "uv": True, "solar": True, "rain": True, "lux": False,
                "battery": True, "last_obs": True, "serial": False,
            }
        }

        self.config = self._load_config()

        self.temp_unit = tk.StringVar(value=self.config["temp_unit"])
        self.wind_unit = tk.StringVar(value=self.config["wind_unit"])
        self.baro_unit = tk.StringVar(value=self.config["baro_unit"])
        self.rain_unit = tk.StringVar(value=self.config["rain_unit"])
        self.always_on_top = tk.BooleanVar(value=self.config["always_on_top"])
        self.dark_mode = tk.BooleanVar(value=self.config["dark_mode"])
        self.font_size = tk.IntVar(value=self.config["font_size"])
        self.temp_font_size = tk.IntVar(value=self.config["temp_font_size"])
        self.use_local_time = tk.BooleanVar(value=self.config["use_local_time"])
        self.time_24h = tk.BooleanVar(value=self.config.get("time_24h", False))
        self.minimize_to_tray = tk.BooleanVar(value=self.config.get("minimize_to_tray", True))
        self.lightning_alert = tk.BooleanVar(value=self.config.get("lightning_alert", True))
        self.autostart = tk.BooleanVar(value=self.config.get("autostart", is_autostart_enabled()))
        self.compact_mode = self.config.get("compact_mode", False)

        self.temp_color = self.config.get("temp_color", "#111111")
        self.humidity_color = self.config.get("humidity_color", "#333333")
        self.rain_color = self.config.get("rain_color", "#1e90ff")

        self.show_fields = {
            k: tk.BooleanVar(value=v) for k, v in self.config["show_fields"].items()
        }

        self.data = {k: None for k in (
            "temp_c", "humidity", "pressure_mb", "wind_avg_mps", "wind_gust_mps",
            "wind_lull_mps", "wind_dir", "rapid_wind_mps", "rapid_wind_dir",
            "uv", "solar_rad", "rain_mm", "illuminance", "battery",
            "last_obs", "last_rapid", "serial", "obs_timestamp",
            "feels_like_c", "dew_point_c", "last_strike_km", "last_strike_ts"
        )}

        self.field_rows = {}
        self.labels = {}
        self.full_geometry = self.config.get("geometry", "460x660")
        self.compact_geometry = self.config.get("compact_geometry", "320x150")
        self.settings_geometry = self.config.get("settings_geometry", "480x720")

        self._drag_data = {"x": 0, "y": 0, "dragging": False}
        self._resize_data = {"x": 0, "y": 0, "w": 0, "h": 0, "resizing": False}
        self.settings_window = None
        self.tray_icon = None
        self._closing = False

        self.root.geometry(self.full_geometry)
        self.root.minsize(320, 110)

        self._setup_style()
        self._build_ui()
        self._apply_theme()

        self.root.update_idletasks()
        try:
            apply_rounded_corners(self.root.winfo_id())
        except Exception:
            pass

        if self.compact_mode:
            self._enter_compact_mode(save=False)

        if IS_WINDOWS and self.autostart.get() != is_autostart_enabled():
            set_autostart(self.autostart.get(), self.script_path)

        self._start_udp_listener()
        if HAS_TRAY:
            self._setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.root.after(800, self._update_display)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def _load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                cfg = {**self.defaults, **loaded}
                if "show_fields" in loaded:
                    cfg["show_fields"] = {**self.defaults["show_fields"], **loaded["show_fields"]}
                return cfg
            except Exception:
                pass
        return self.defaults.copy()

    def _save_config(self):
        if self.compact_mode:
            self.compact_geometry = self.root.geometry()
        else:
            self.full_geometry = self.root.geometry()
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_geometry = self.settings_window.geometry()

        cfg = {
            "temp_unit": self.temp_unit.get(),
            "wind_unit": self.wind_unit.get(),
            "baro_unit": self.baro_unit.get(),
            "rain_unit": self.rain_unit.get(),
            "always_on_top": self.always_on_top.get(),
            "dark_mode": self.dark_mode.get(),
            "font_size": self.font_size.get(),
            "temp_font_size": self.temp_font_size.get(),
            "use_local_time": self.use_local_time.get(),
            "time_24h": self.time_24h.get(),
            "geometry": self.full_geometry,
            "compact_geometry": self.compact_geometry,
            "settings_geometry": self.settings_geometry,
            "compact_mode": self.compact_mode,
            "temp_color": self.temp_color,
            "humidity_color": self.humidity_color,
            "rain_color": self.rain_color,
            "minimize_to_tray": self.minimize_to_tray.get(),
            "lightning_alert": self.lightning_alert.get(),
            "autostart": self.autostart.get(),
            "show_fields": {k: v.get() for k, v in self.show_fields.items()},
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f"Could not save config: {e}")

    def _on_close_request(self):
        if HAS_TRAY and self.minimize_to_tray.get() and not self._closing:
            self._hide_to_tray()
        else:
            self._quit_app()

    def _quit_app(self):
        self._closing = True
        self._save_config()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------
    def _setup_tray(self):
        def on_show(icon, item):
            self.root.after(0, self._show_from_tray)

        def on_quit(icon, item):
            self.root.after(0, self._quit_app)

        menu = pystray.Menu(
            pystray.MenuItem("Show", on_show, default=True),
            pystray.MenuItem("Quit", on_quit),
        )
        self.tray_icon = pystray.Icon("local_tempest_wx", make_tray_image(), APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _hide_to_tray(self):
        self.root.withdraw()

    def _show_from_tray(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self.compact_mode:
            self.root.overrideredirect(True)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _setup_style(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

    def _apply_theme(self):
        dark = self.dark_mode.get()
        if dark:
            bg, fg = "#1e1e1e", "#e0e0e0"
            header_fg, accent = "#aaaaaa", "#3a3a3a"
            status_ok, status_err = "#4caf50", "#ef5350"
            grip_fg = "#666666"
            settings_bg, settings_accent = "#252526", "#4fc3f7"
            btn_fg = "#111111"
        else:
            bg, fg = "#f5f5f5", "#222222"
            header_fg, accent = "#555555", "#e0e0e0"
            status_ok, status_err = "#2a7a2a", "#c00"
            grip_fg = "#999999"
            settings_bg, settings_accent = "#e8f0fe", "#1a73e8"
            btn_fg = "white"

        self.root.configure(bg=bg)
        for s in (".", "TFrame", "TLabel", "TCheckbutton", "TRadiobutton",
                  "TLabelframe", "TLabelframe.Label", "TScale"):
            self.style.configure(s, background=bg, foreground=fg)

        self.style.configure("TButton", background=accent, foreground=fg)
        self.style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"),
                             foreground=header_fg, background=bg)
        self.style.configure("Value.TLabel", font=("Segoe UI", self.font_size.get()),
                             foreground=fg, background=bg)
        self.style.configure("Rain.TLabel", font=("Segoe UI", self.font_size.get(), "bold"),
                             foreground=self.rain_color, background=bg)
        self.style.configure("Big.TLabel", font=("Segoe UI", self.temp_font_size.get(), "bold"),
                             foreground=self.temp_color, background=bg)
        self.style.configure("Unit.TLabel", font=("Segoe UI", 11),
                             foreground=header_fg, background=bg)
        self.style.configure("Humidity.TLabel", font=("Segoe UI", self.font_size.get()),
                             foreground=self.humidity_color, background=bg)
        self.style.configure("Status.TLabel", font=("Segoe UI", 9), background=bg)
        self.style.configure("Grip.TLabel", font=("Segoe UI", 10),
                             foreground=grip_fg, background=bg)

        self.style.configure("Settings.TFrame", background=settings_bg)
        self.style.configure("Settings.TLabelframe", background=settings_bg, foreground=fg)
        self.style.configure("Settings.TLabelframe.Label", background=settings_bg,
                             foreground=settings_accent, font=("Segoe UI", 10, "bold"))
        self.style.configure("Settings.TLabel", background=settings_bg, foreground=fg)
        self.style.configure("Settings.TCheckbutton", background=settings_bg, foreground=fg)
        self.style.configure("Settings.TRadiobutton", background=settings_bg, foreground=fg)
        self.style.configure("Settings.TButton", background=settings_accent, foreground=btn_fg)

        self.status_label.configure(style="Status.TLabel")
        self.big_temp.configure(style="Big.TLabel")
        self.big_temp_unit.configure(style="Unit.TLabel")
        self.feels_label.configure(style="Humidity.TLabel")
        self.compact_rain_label.configure(style="Humidity.TLabel")
        self.humidity_label.configure(style="Humidity.TLabel")
        self.rapid_label.configure(style="Humidity.TLabel")
        if hasattr(self, "resize_grip"):
            self.resize_grip.configure(style="Grip.TLabel")

        rain_active = (self.data.get("rain_mm") or 0) > 0
        for key, (name_lbl, val_lbl) in self.field_rows.items():
            name_lbl.configure(style="Header.TLabel")
            if key == "rain" and rain_active:
                val_lbl.configure(style="Rain.TLabel")
            else:
                val_lbl.configure(style="Value.TLabel")

        self._status_colors = {"ok": status_ok, "err": status_err}
        self._settings_bg = settings_bg

    # ------------------------------------------------------------------
    # Main UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.top = ttk.Frame(self.root, padding=(10, 8))
        self.top.pack(fill="x")

        ttk.Checkbutton(self.top, text="Always on top", variable=self.always_on_top,
                        command=self._toggle_always_on_top).pack(side="left")
        ttk.Checkbutton(self.top, text="Dark mode", variable=self.dark_mode,
                        command=self._on_theme_change).pack(side="left", padx=(12, 0))

        self.prefs_btn = ttk.Button(self.top, text="⚙ Settings", width=10,
                                    command=self._toggle_settings)
        self.prefs_btn.pack(side="left", padx=(12, 0))
        ttk.Button(self.top, text="About", width=7, command=self._show_about).pack(side="left", padx=(8, 0))

        self.status_label = ttk.Label(self.top, text="Waiting for data…", style="Status.TLabel")
        self.status_label.pack(side="right")

        self.main = ttk.Frame(self.root, padding=(14, 8))
        self.main.pack(fill="both", expand=True)

        self.temp_frame = ttk.Frame(self.main)
        self.temp_frame.pack(fill="x", pady=(2, 4))

        # Left: big temp + feels like + rain (always visible)
        left = ttk.Frame(self.temp_frame)
        left.pack(side="left")

        temp_row = ttk.Frame(left)
        temp_row.pack(anchor="w")
        self.big_temp = ttk.Label(temp_row, text="—", style="Big.TLabel", cursor="hand2")
        self.big_temp.pack(side="left")
        self.big_temp_unit = ttk.Label(temp_row, text="", style="Unit.TLabel", cursor="hand2")
        self.big_temp_unit.pack(side="left", padx=(6, 0), pady=(12, 0))

        self.feels_label = ttk.Label(left, text="", style="Humidity.TLabel", cursor="hand2")
        self.feels_label.pack(anchor="w", pady=(2, 0))

        self.compact_rain_label = ttk.Label(left, text="", style="Humidity.TLabel", cursor="hand2")
        self.compact_rain_label.pack(anchor="w")

        # Right: humidity + rapid wind
        right = ttk.Frame(self.temp_frame)
        right.pack(side="right", pady=(8, 0))
        self.humidity_label = ttk.Label(right, text="", style="Humidity.TLabel", cursor="hand2")
        self.humidity_label.pack(anchor="e")
        self.rapid_label = ttk.Label(right, text="", style="Humidity.TLabel", cursor="hand2")
        self.rapid_label.pack(anchor="e")

        for w in (self.big_temp, self.big_temp_unit, self.feels_label,
                  self.compact_rain_label, self.humidity_label, self.rapid_label):
            w.bind("<Button-1>", self._on_temp_press)
            w.bind("<B1-Motion>", self._on_temp_drag)
            w.bind("<ButtonRelease-1>", self._on_temp_release)

        self.separator = ttk.Separator(self.main, orient="horizontal")
        self.separator.pack(fill="x", pady=8)

        self.grid = ttk.Frame(self.main)
        self.grid.pack(fill="both", expand=True)
        self.grid.columnconfigure(1, weight=1)

        self.resize_grip = ttk.Label(self.root, text="⋰", style="Grip.TLabel", cursor="sizing")
        self.resize_grip.bind("<Button-1>", self._on_resize_press)
        self.resize_grip.bind("<B1-Motion>", self._on_resize_drag)
        self.resize_grip.bind("<ButtonRelease-1>", self._on_resize_release)

        self._rebuild_fields()
        if self.always_on_top.get():
            self.root.attributes("-topmost", True)

    def _rebuild_fields(self):
        for w in self.grid.winfo_children():
            w.destroy()
        self.field_rows.clear()
        self.labels.clear()

        rows = [
            ("pressure", "Pressure"),
            ("feels_like", "Feels Like"),
            ("dew_point", "Dew Point"),
            ("wind_avg", "Wind Average"),
            ("wind_gust", "Wind Gust"),
            ("wind_lull", "Wind Lull"),
            ("wind_dir", "Direction"),
            ("rapid_wind", "Rapid Wind"),
            ("uv", "UV Index"),
            ("solar", "Solar Radiation"),
            ("rain", "Rain"),
            ("lux", "Illuminance"),
            ("battery", "Battery"),
            ("last_obs", "Last Observation"),
            ("serial", "Device"),
        ]

        row_idx = 0
        for key, name in rows:
            if key not in self.show_fields or not self.show_fields[key].get():
                continue

            name_lbl = ttk.Label(self.grid, text=name, style="Header.TLabel")
            name_lbl.grid(row=row_idx, column=0, sticky="w", pady=3, padx=(0, 14))
            val_lbl = ttk.Label(self.grid, text="—", style="Value.TLabel")
            val_lbl.grid(row=row_idx, column=1, sticky="w", pady=3)
            self.field_rows[key] = (name_lbl, val_lbl)
            self.labels[key] = val_lbl
            row_idx += 1

        self._apply_theme()
        self._update_display()
        self._save_config()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _toggle_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self._close_settings()
        else:
            self._open_settings()

    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.minsize(420, 520)
        win.configure(bg=self._settings_bg)
        win.transient(self.root)
        self.settings_window = win
        self.prefs_btn.config(text="⚙ Close")

        self.root.update_idletasks()
        mx, my, mw = self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width()
        try:
            size = self.settings_geometry.split("+")[0].split("-")[0]
            w, h = map(int, size.lower().split("x"))
        except Exception:
            w, h = 480, 720
        nx = mx + mw + 16
        ny = my
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if nx + w > sw:
            nx = max(0, mx - w - 16)
        if ny + h > sh:
            ny = max(0, sh - h - 40)
        win.geometry(f"{w}x{h}+{nx}+{ny}")
        try:
            apply_rounded_corners(win.winfo_id())
        except Exception:
            pass

        container = ttk.Frame(win, style="Settings.TFrame", padding=14)
        container.pack(fill="both", expand=True)

        beh = ttk.LabelFrame(container, text="Behavior", style="Settings.TLabelframe", padding=10)
        beh.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(beh, text="Minimize to system tray on close",
                        variable=self.minimize_to_tray, style="Settings.TCheckbutton",
                        command=self._pref_changed).pack(anchor="w")
        if not HAS_TRAY:
            ttk.Label(beh, text="(Install pystray + Pillow for tray support)",
                      style="Settings.TLabel").pack(anchor="w")
        ttk.Checkbutton(beh, text="Lightning strike sound alert",
                        variable=self.lightning_alert, style="Settings.TCheckbutton",
                        command=self._pref_changed).pack(anchor="w")
        if IS_WINDOWS:
            ttk.Checkbutton(beh, text="Start with Windows",
                            variable=self.autostart, style="Settings.TCheckbutton",
                            command=self._toggle_autostart).pack(anchor="w")
        else:
            ttk.Label(beh, text="(Autostart is Windows-only)",
                      style="Settings.TLabel").pack(anchor="w")

        uf = ttk.LabelFrame(container, text="Units", style="Settings.TLabelframe", padding=10)
        uf.pack(fill="x", pady=(0, 8))
        ttk.Label(uf, text="Temperature", style="Settings.TLabel").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Radiobutton(uf, text="°F", variable=self.temp_unit, value="F",
                        style="Settings.TRadiobutton", command=self._pref_changed).grid(row=0, column=1, padx=6)
        ttk.Radiobutton(uf, text="°C", variable=self.temp_unit, value="C",
                        style="Settings.TRadiobutton", command=self._pref_changed).grid(row=0, column=2, padx=6)
        ttk.Label(uf, text="Wind", style="Settings.TLabel").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        for i, u in enumerate(["mph", "km/h", "m/s", "kts"]):
            ttk.Radiobutton(uf, text=u, variable=self.wind_unit, value=u,
                            style="Settings.TRadiobutton", command=self._pref_changed).grid(row=1, column=i+1, padx=4)
        ttk.Label(uf, text="Pressure", style="Settings.TLabel").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        for i, u in enumerate(["inHg", "mb", "mmHg"]):
            ttk.Radiobutton(uf, text=u, variable=self.baro_unit, value=u,
                            style="Settings.TRadiobutton", command=self._pref_changed).grid(row=2, column=i+1, padx=4)
        ttk.Label(uf, text="Rain", style="Settings.TLabel").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        ttk.Radiobutton(uf, text="inches", variable=self.rain_unit, value="in",
                        style="Settings.TRadiobutton", command=self._pref_changed).grid(row=3, column=1, padx=6)
        ttk.Radiobutton(uf, text="mm", variable=self.rain_unit, value="mm",
                        style="Settings.TRadiobutton", command=self._pref_changed).grid(row=3, column=2, padx=6)

        tf = ttk.LabelFrame(container, text="Time", style="Settings.TLabelframe", padding=10)
        tf.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(tf, text="Local time (vs UTC)", variable=self.use_local_time,
                        style="Settings.TCheckbutton", command=self._pref_changed).pack(anchor="w")
        ttk.Checkbutton(tf, text="24-hour clock", variable=self.time_24h,
                        style="Settings.TCheckbutton", command=self._pref_changed).pack(anchor="w")

        cf = ttk.LabelFrame(container, text="Colors", style="Settings.TLabelframe", padding=10)
        cf.pack(fill="x", pady=(0, 8))
        ttk.Label(cf, text="Temperature:", style="Settings.TLabel").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.temp_color_btn = tk.Button(cf, text="  Choose  ", bg=self.temp_color,
                                        command=self._choose_temp_color, relief="groove")
        self.temp_color_btn.grid(row=0, column=1, padx=8, pady=3)
        ttk.Label(cf, text="Humidity / Rapid:", style="Settings.TLabel").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self.humidity_color_btn = tk.Button(cf, text="  Choose  ", bg=self.humidity_color,
                                            command=self._choose_humidity_color, relief="groove")
        self.humidity_color_btn.grid(row=1, column=1, padx=8, pady=3)
        ttk.Label(cf, text="Rain attention:", style="Settings.TLabel").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.rain_color_btn = tk.Button(cf, text="  Choose  ", bg=self.rain_color,
                                        command=self._choose_rain_color, relief="groove")
        self.rain_color_btn.grid(row=2, column=1, padx=8, pady=3)

        ff = ttk.LabelFrame(container, text="Font Sizes", style="Settings.TLabelframe", padding=10)
        ff.pack(fill="x", pady=(0, 8))
        ttk.Label(ff, text="Value font:", style="Settings.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Scale(ff, from_=10, to=18, orient="horizontal", variable=self.font_size,
                  command=self._on_font_change).grid(row=0, column=1, sticky="ew", padx=8)
        self.font_label = ttk.Label(ff, text=str(self.font_size.get()), style="Settings.TLabel")
        self.font_label.grid(row=0, column=2)
        ttk.Label(ff, text="Temperature font:", style="Settings.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(ff, from_=18, to=48, orient="horizontal", variable=self.temp_font_size,
                  command=self._on_temp_font_change).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        self.temp_font_label = ttk.Label(ff, text=str(self.temp_font_size.get()), style="Settings.TLabel")
        self.temp_font_label.grid(row=1, column=2, pady=(8, 0))
        ff.columnconfigure(1, weight=1)

        fields = ttk.LabelFrame(container, text="Show Fields", style="Settings.TLabelframe", padding=10)
        fields.pack(fill="x", pady=(0, 8))
        names = [
            ("pressure", "Pressure"), ("feels_like", "Feels Like (list)"),
            ("dew_point", "Dew Point"), ("wind_avg", "Wind Average"),
            ("wind_gust", "Wind Gust"), ("wind_lull", "Wind Lull"),
            ("wind_dir", "Direction"), ("rapid_wind", "Rapid Wind (list)"),
            ("uv", "UV Index"), ("solar", "Solar Radiation"),
            ("rain", "Rain"), ("lux", "Illuminance"),
            ("battery", "Battery"), ("last_obs", "Last Observation"),
            ("serial", "Device"),
        ]
        for i, (key, name) in enumerate(names):
            if key not in self.show_fields:
                self.show_fields[key] = tk.BooleanVar(value=True)
            ttk.Checkbutton(fields, text=name, variable=self.show_fields[key],
                            style="Settings.TCheckbutton",
                            command=self._rebuild_fields).grid(
                row=i // 2, column=i % 2, sticky="w", padx=10, pady=3)

        win.protocol("WM_DELETE_WINDOW", self._close_settings)
        win.bind("<Configure>", self._on_settings_configure)

    def _on_settings_configure(self, event):
        if self.settings_window and event.widget == self.settings_window:
            self.settings_geometry = self.settings_window.geometry()

    def _close_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_geometry = self.settings_window.geometry()
            self._save_config()
            self.settings_window.destroy()
        self.settings_window = None
        self.prefs_btn.config(text="⚙ Settings")

    def _toggle_autostart(self):
        if not IS_WINDOWS:
            return
        ok = set_autostart(self.autostart.get(), self.script_path)
        if not ok:
            self.autostart.set(not self.autostart.get())
        self._save_config()

    def _choose_temp_color(self):
        c = colorchooser.askcolor(color=self.temp_color, title="Temperature Color")
        if c[1]:
            self.temp_color = c[1]
            self.temp_color_btn.configure(bg=self.temp_color)
            self._apply_theme()
            self._save_config()

    def _choose_humidity_color(self):
        c = colorchooser.askcolor(color=self.humidity_color, title="Humidity / Rapid Color")
        if c[1]:
            self.humidity_color = c[1]
            self.humidity_color_btn.configure(bg=self.humidity_color)
            self._apply_theme()
            self._save_config()

    def _choose_rain_color(self):
        c = colorchooser.askcolor(color=self.rain_color, title="Rain Attention Color")
        if c[1]:
            self.rain_color = c[1]
            self.rain_color_btn.configure(bg=self.rain_color)
            self._apply_theme()
            self._save_config()

    def _show_about(self):
        about = tk.Toplevel(self.root)
        about.title("About")
        about.resizable(False, False)
        about.transient(self.root)
        about.grab_set()
        self.root.update_idletasks()
        about.geometry(f"360x250+{self.root.winfo_x() + 50}+{self.root.winfo_y() + 70}")
        try:
            apply_rounded_corners(about.winfo_id())
        except Exception:
            pass
        f = ttk.Frame(about, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=APP_NAME, font=("Segoe UI", 15, "bold")).pack(pady=(0, 2))
        ttk.Label(f, text=f"Version {APP_VERSION}").pack(pady=(0, 12))
        ttk.Label(f, text=f"by {AUTHOR}").pack()
        ttk.Label(f, text=AUTHOR_EMAIL).pack(pady=(2, 8))
        link = ttk.Label(f, text=AUTHOR_URL, foreground="#1a73e8", cursor="hand2")
        link.pack(pady=(0, 14))
        link.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_URL))
        ttk.Button(f, text="Close", command=about.destroy).pack()

    # ------------------------------------------------------------------
    # Compact / drag / resize
    # ------------------------------------------------------------------
    def _on_temp_press(self, event):
        self._drag_data.update(x=event.x, y=event.y, dragging=False)

    def _on_temp_drag(self, event):
        if not self.compact_mode:
            return
        dx, dy = event.x - self._drag_data["x"], event.y - self._drag_data["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_data["dragging"] = True
            self.root.geometry(f"+{self.root.winfo_x() + dx}+{self.root.winfo_y() + dy}")

    def _on_temp_release(self, event):
        if not self._drag_data.get("dragging"):
            self._toggle_compact()
        self._drag_data["dragging"] = False

    def _on_resize_press(self, event):
        self._resize_data.update(
            x=event.x_root, y=event.y_root,
            w=self.root.winfo_width(), h=self.root.winfo_height(), resizing=True)

    def _on_resize_drag(self, event):
        if not self._resize_data.get("resizing"):
            return
        dx = event.x_root - self._resize_data["x"]
        dy = event.y_root - self._resize_data["y"]
        self.root.geometry(
            f"{max(200, self._resize_data['w'] + dx)}x{max(110, self._resize_data['h'] + dy)}")

    def _on_resize_release(self, event):
        self._resize_data["resizing"] = False
        self._save_config()

    def _toggle_compact(self, event=None):
        if self.compact_mode:
            self._exit_compact_mode()
        else:
            self._enter_compact_mode()

    def _enter_compact_mode(self, save=True):
        self.compact_mode = True
        self.full_geometry = self.root.geometry()
        self.top.pack_forget()
        self.separator.pack_forget()
        self.grid.pack_forget()
        self.root.overrideredirect(True)
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-2, y=-1)
        self.root.geometry(self.compact_geometry)
        self.root.minsize(200, 110)
        if save:
            self._save_config()

    def _exit_compact_mode(self):
        self.compact_mode = False
        self.compact_geometry = self.root.geometry()
        self.resize_grip.place_forget()
        self.root.overrideredirect(False)
        self.top.pack(fill="x")
        self.separator.pack(fill="x", pady=8)
        self.grid.pack(fill="both", expand=True)
        self.root.geometry(self.full_geometry)
        self.root.minsize(360, 480)
        try:
            apply_rounded_corners(self.root.winfo_id())
        except Exception:
            pass
        self._save_config()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def _toggle_always_on_top(self):
        self.root.attributes("-topmost", self.always_on_top.get())
        self._save_config()

    def _on_theme_change(self):
        self._apply_theme()
        self._save_config()
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.configure(bg=self._settings_bg)

    def _on_font_change(self, _=None):
        size = int(self.font_size.get())
        if hasattr(self, "font_label"):
            self.font_label.config(text=str(size))
        self.style.configure("Value.TLabel", font=("Segoe UI", size))
        self.style.configure("Rain.TLabel", font=("Segoe UI", size, "bold"))
        self.style.configure("Humidity.TLabel", font=("Segoe UI", size))
        self._update_display()
        self._save_config()

    def _on_temp_font_change(self, _=None):
        size = int(self.temp_font_size.get())
        if hasattr(self, "temp_font_label"):
            self.temp_font_label.config(text=str(size))
        self.style.configure("Big.TLabel", font=("Segoe UI", size, "bold"))
        self._update_display()
        self._save_config()

    def _pref_changed(self):
        self._update_display()
        self._save_config()

    def _play_lightning_alert(self):
        if self.lightning_alert.get():
            play_alert()

    # ------------------------------------------------------------------
    # UDP
    # ------------------------------------------------------------------
    def _start_udp_listener(self):
        def listen():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("", UDP_PORT))
            except OSError as e:
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Bind error: {e}", foreground=self._status_colors["err"]))
                return
            self.root.after(0, lambda: self.status_label.config(
                text="Listening • UDP 50222", foreground=self._status_colors["ok"]))
            while True:
                try:
                    data, _ = sock.recvfrom(BUFFER_SIZE)
                    self._process_message(json.loads(data.decode("utf-8")))
                except Exception:
                    pass
        threading.Thread(target=listen, daemon=True).start()

    def _process_message(self, msg):
        mtype = msg.get("type")

        if mtype == "obs_st":
            obs = msg.get("obs", [[]])[0]
            if len(obs) >= 18:
                temp_c = obs[7]
                rh = obs[8]
                wind_avg = obs[2]
                self.data.update({
                    "serial": msg.get("serial_number"),
                    "wind_lull_mps": obs[1], "wind_avg_mps": wind_avg,
                    "wind_gust_mps": obs[3], "wind_dir": obs[4],
                    "pressure_mb": obs[6], "temp_c": temp_c, "humidity": rh,
                    "illuminance": obs[9], "uv": obs[10], "solar_rad": obs[11],
                    "rain_mm": obs[12], "battery": obs[16], "obs_timestamp": obs[0],
                    "dew_point_c": dew_point_c(temp_c, rh),
                    "feels_like_c": feels_like_c(temp_c, rh, wind_avg),
                })

        elif mtype == "rapid_wind":
            ob = msg.get("ob", [])
            if len(ob) >= 3:
                self.data.update({
                    "rapid_wind_mps": ob[1], "rapid_wind_dir": ob[2],
                    "last_rapid": datetime.fromtimestamp(ob[0], UTC).strftime("%H:%M:%S UTC"),
                })
                if self.data.get("temp_c") is not None:
                    self.data["feels_like_c"] = feels_like_c(
                        self.data["temp_c"], self.data.get("humidity"), ob[1])

        elif mtype == "evt_strike":
            evt = msg.get("evt", [])
            if len(evt) >= 2:
                self.data["last_strike_ts"] = evt[0]
                self.data["last_strike_km"] = evt[1]
                self.root.after(0, self._play_lightning_alert)
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Lightning ~{evt[1]} km", foreground="#ff9800"))

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------
    def _fmt_temp(self, c):
        if c is None:
            return "—", ""
        if self.temp_unit.get() == "F":
            return f"{c_to_f(c):.1f}", "°F"
        return f"{c:.1f}", "°C"

    def _fmt_temp_value(self, c):
        if c is None:
            return "—"
        if self.temp_unit.get() == "F":
            return f"{c_to_f(c):.1f} °F"
        return f"{c:.1f} °C"

    def _fmt_wind(self, mps):
        if mps is None:
            return "—"
        u = self.wind_unit.get()
        if u == "mph": return f"{mps_to_mph(mps):.1f} mph"
        if u == "km/h": return f"{mps_to_kmh(mps):.1f} km/h"
        if u == "kts": return f"{mps_to_kts(mps):.1f} kts"
        return f"{mps:.1f} m/s"

    def _fmt_pressure(self, mb):
        if mb is None:
            return "—"
        u = self.baro_unit.get()
        if u == "inHg": return f"{mb_to_inhg(mb):.2f} inHg"
        if u == "mmHg": return f"{mb_to_mmhg(mb):.1f} mmHg"
        return f"{mb:.1f} mb"

    def _fmt_rain(self, mm):
        if mm is None or mm <= 0:
            return "No rain"
        if self.rain_unit.get() == "in":
            return f"{mm_to_inches(mm):.3f} in"
        return f"{mm:.2f} mm"

    def _fmt_last_obs(self):
        ts = self.data.get("obs_timestamp")
        if ts is None:
            return "—"
        if self.use_local_time.get():
            dt = datetime.fromtimestamp(ts)
            if self.time_24h.get():
                return dt.strftime("%H:%M:%S")
            s = dt.strftime("%I:%M:%S %p")
            return s[1:] if s.startswith("0") else s
        dt = datetime.fromtimestamp(ts, UTC)
        if self.time_24h.get():
            return dt.strftime("%H:%M:%S UTC")
        s = dt.strftime("%I:%M:%S %p UTC")
        return s[1:] if s.startswith("0") else s

    # ------------------------------------------------------------------
    # Display update
    # ------------------------------------------------------------------
    def _update_display(self):
        d = self.data
        val, unit = self._fmt_temp(d["temp_c"])
        self.big_temp.config(text=val)
        self.big_temp_unit.config(text=unit)

        fl = d.get("feels_like_c")
        self.feels_label.config(
            text=f"feels like {self._fmt_temp_value(fl)}" if fl is not None else "")

        # Compact / top rain (always visible)
        rain_txt = self._fmt_rain(d["rain_mm"])
        rain_active = (d["rain_mm"] or 0) > 0
        self.compact_rain_label.config(
            text=rain_txt,
            style="Rain.TLabel" if rain_active else "Humidity.TLabel"
        )

        self.humidity_label.config(
            text=f"{d['humidity']:.0f}% humidity" if d["humidity"] is not None else "")

        if d["rapid_wind_mps"] is not None:
            self.rapid_label.config(
                text=f"{self._fmt_wind(d['rapid_wind_mps'])} {degrees_to_compass(d['rapid_wind_dir'])}")
        else:
            self.rapid_label.config(text="")

        def set_val(key, text):
            if key in self.labels:
                self.labels[key].config(text=text)

        set_val("pressure", self._fmt_pressure(d["pressure_mb"]))
        set_val("feels_like", self._fmt_temp_value(d.get("feels_like_c")))
        set_val("dew_point", self._fmt_temp_value(d.get("dew_point_c")))
        set_val("wind_avg", self._fmt_wind(d["wind_avg_mps"]))
        set_val("wind_gust", self._fmt_wind(d["wind_gust_mps"]))
        set_val("wind_lull", self._fmt_wind(d["wind_lull_mps"]))

        dir_val = d["rapid_wind_dir"] if d["rapid_wind_dir"] is not None else d["wind_dir"]
        set_val("wind_dir", f"{degrees_to_compass(dir_val)}  ({dir_val}°)" if dir_val is not None else "—")

        if d["rapid_wind_mps"] is not None:
            set_val("rapid_wind", f"{self._fmt_wind(d['rapid_wind_mps'])}  {degrees_to_compass(d['rapid_wind_dir'])}")
        else:
            set_val("rapid_wind", "—")

        set_val("uv", f"{d['uv']:.1f}" if d["uv"] is not None else "—")
        set_val("solar", f"{d['solar_rad']:.0f} W/m²" if d["solar_rad"] is not None else "—")
        set_val("rain", rain_txt)
        if "rain" in self.labels:
            self.labels["rain"].configure(style="Rain.TLabel" if rain_active else "Value.TLabel")

        set_val("lux", f"{d['illuminance']:,.0f} lux" if d["illuminance"] is not None else "—")
        set_val("battery", f"{d['battery']:.2f} V" if d["battery"] is not None else "—")
        set_val("last_obs", self._fmt_last_obs())
        set_val("serial", d["serial"] or "—")

        if d["obs_timestamp"] or d["last_rapid"]:
            cur = self.status_label.cget("text")
            if not cur.startswith("Lightning"):
                self.status_label.config(text="Receiving data", foreground=self._status_colors["ok"])

        self.root.after(800, self._update_display)

def main():
    root = tk.Tk()
    TempestDisplay(root)
    root.mainloop()

if __name__ == "__main__":
    main()