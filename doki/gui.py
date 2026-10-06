"""The doki window."""

import base64
import ctypes
import os
import queue
import sys
import threading
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

from . import anime4k
from .capture import capture_page
from .hls import make_quality_options, parse_hls_subtitle_tracks, parse_hls_variants
from .library import (
    add_history_entry,
    format_timestamp,
    is_finished,
    make_resume_arguments,
    next_episode_url,
    read_resume_position,
    remove_history_entry,
    watch_progress,
)
from .mpv import find_mpv_executable, launch_in_new_powershell, launch_mpv, make_mpv_arguments, make_mpv_command
from .paths import IS_MAC, data_path, load_json, resource_path, save_json
from .updates import check_for_update
from .subtitles import (
    language_name,
    make_subtitle_options,
    preferred_subtitle_label,
    remove_stale_subtitles,
    save_captured_subtitle,
)


def register_mac_fonts(font_paths):
    """Makes bundled fonts available to this process through Core Text."""
    core_foundation = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    core_text = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreText.framework/CoreText")
    core_foundation.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
    core_foundation.CFURLCreateFromFileSystemRepresentation.argtypes = (
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool,
    )
    core_foundation.CFRelease.argtypes = (ctypes.c_void_p,)
    core_text.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
    core_text.CTFontManagerRegisterFontsForURL.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p)
    for font_path in font_paths:
        encoded = os.fsencode(font_path)
        url = core_foundation.CFURLCreateFromFileSystemRepresentation(None, encoded, len(encoded), False)
        if not url:
            continue
        # 1 = kCTFontManagerScopeProcess
        if not core_text.CTFontManagerRegisterFontsForURL(url, 1, None):
            print(f"[gui] Could not load bundled font {font_path}", file=sys.stderr)
        core_foundation.CFRelease(url)


class M3u8App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.capture_result = None
        self.stream_url = None
        self.headers = {}
        self.playlist_text = ""
        self.subtitle_responses = {}
        self.quality_options = {}
        self.subtitle_options = {}
        self.page_title = ""
        self.settings = load_json("settings.json", {})
        self.history = load_json("history.json", [])
        self.recent_options = {}

        root.title("doki")
        root.geometry("840x862")
        root.minsize(720, 862)
        if not IS_MAC:
            # macOS keeps its native title bar; borderless windows there can't take keyboard focus.
            root.overrideredirect(True)
        root.configure(bg="#d8cdbd")

        style = ttk.Style(root)
        style.theme_use("clam")
        font_directory = resource_path("assets", "jetbrains mono nerd font")
        if os.name == "nt":
            add_font = ctypes.windll.gdi32.AddFontResourceExW
            add_font.argtypes = (ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
            add_font.restype = ctypes.c_int
            for font_file in ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"):
                font_path = os.path.join(font_directory, font_file)
                if os.path.isfile(font_path) and not add_font(font_path, 0x10, None):
                    print(
                        f"[gui] Could not load bundled font {font_file}: {ctypes.WinError()}",
                        file=sys.stderr,
                    )
        elif IS_MAC:
            try:
                register_mac_fonts([
                    os.path.join(font_directory, font_file)
                    for font_file in ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf")
                ])
            except (OSError, AttributeError) as error:
                print(f"[gui] Could not load bundled fonts: {error}", file=sys.stderr)
        available_fonts = set(tkfont.families(root))
        requested_font = next(
            (
                name for name in (
                    "JetBrainsMono Nerd Font",
                    "JetBrainsMono NF",
                    "JetBrains Mono Nerd Font",
                    "JetBrains Mono",
                )
                if name in available_fonts
            ),
            None,
        )
        if requested_font:
            font_family = requested_font
        elif "Cascadia Code" in available_fonts:
            font_family = "Cascadia Code"
            print(
                "[gui] JetBrains Mono Nerd Font is not installed; using Cascadia Code. "
                "Install JetBrains Mono Nerd Font to use it throughout the app.",
                file=sys.stderr,
            )
        elif "Consolas" in available_fonts:
            font_family = "Consolas"
            print(
                "[gui] JetBrains Mono Nerd Font is not installed; using Consolas. "
                "Install JetBrains Mono Nerd Font to use it throughout the app.",
                file=sys.stderr,
            )
        elif "Menlo" in available_fonts:
            font_family = "Menlo"
        else:
            font_family = "TkDefaultFont"
            print(
                "[gui] JetBrains Mono Nerd Font is not installed; using the system Tk font. "
                "Install JetBrains Mono Nerd Font to use it throughout the app.",
                file=sys.stderr,
            )
        for named_font in (
            "TkDefaultFont",
            "TkTextFont",
            "TkFixedFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
        ):
            tkfont.nametofont(named_font, root=root).configure(family=font_family)
        root.option_add("*Font", (font_family, 10))
        background = "#f5f0e7"
        card = "#fffdf8"
        ink = "#34443c"
        muted = "#78847a"
        green = "#557a68"
        chrome = "#34443c"
        style.configure("App.TFrame", background=background)
        style.configure("Card.TLabelframe", background=card, bordercolor="#e4ddd0", relief="solid", borderwidth=1)
        style.configure(
            "Card.TLabelframe.Label",
            background=card,
            foreground=ink,
            font=(font_family, 11, "bold"),
            padding=(4, 0),
        )
        style.configure("Card.TFrame", background=card)
        style.configure("TLabel", background=card, foreground=ink, font=(font_family, 10))
        style.configure("Eyebrow.TLabel", background=background, foreground=green, font=(font_family, 9, "bold"))
        style.configure("Title.TLabel", background=background, foreground=ink, font=(font_family, 25, "bold"))
        style.configure("Subtitle.TLabel", background=background, foreground=muted, font=(font_family, 10))
        style.configure("Muted.TLabel", background=background, foreground=muted, font=(font_family, 9))
        style.configure("Hint.TLabel", background=card, foreground=muted, font=(font_family, 9))
        style.configure("Muted.TCheckbutton", background=background, foreground=muted, font=(font_family, 9))
        style.map("Muted.TCheckbutton", background=[("active", background)], indicatorcolor=[("selected", green), ("!selected", card)])
        style.configure("TButton", font=(font_family, 10, "bold"), padding=(14, 9), background="#e9e4d9", foreground=ink, borderwidth=0)
        style.map(
            "TButton",
            background=[("pressed", "#d6d0c5"), ("active", "#ded8cc"), ("disabled", "#ebe7df")],
            foreground=[("disabled", "#a6a69e")],
        )
        style.configure("Primary.TButton", font=(font_family, 10, "bold"), padding=(18, 11), background=green, foreground="#ffffff", borderwidth=0)
        style.map(
            "Primary.TButton",
            background=[("disabled", "#b8c5bc"), ("pressed", "#426553"), ("active", "#628774")],
            foreground=[("disabled", "#f5f5f0")],
        )
        style.configure("TEntry", padding=(10, 9), fieldbackground=card, foreground=ink, bordercolor="#ded8cc", lightcolor="#ded8cc", darkcolor="#ded8cc")
        style.map("TEntry", bordercolor=[("focus", green)], lightcolor=[("focus", green)], darkcolor=[("focus", green)])
        style.configure("TCombobox", padding=(9, 7), fieldbackground=card, foreground=ink, background="#eee9df", arrowcolor=green)
        style.map("TCombobox", fieldbackground=[("readonly", card)], foreground=[("readonly", ink)], background=[("active", "#e2ddd2")])
        style.configure("TSpinbox", padding=(8, 6), fieldbackground=card, foreground=ink, arrowcolor=green)
        style.configure("Warm.Horizontal.TProgressbar", troughcolor="#e8e1d5", background=green, bordercolor="#e8e1d5", lightcolor=green, darkcolor=green)

        self.url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.quality_var = tk.StringVar(value="Auto (mpv default)")
        self.subtitle_var = tk.StringVar(value="No subtitles")
        self.cache_var = tk.StringVar(value=str(self.settings.get("cache_secs", 1300)))
        self.buffer_var = tk.StringVar(value=str(self.settings.get("initial_buffer", 8)))
        self.recent_var = tk.StringVar()
        self.debug_var = tk.BooleanVar(value=bool(self.settings.get("debug_console", False)))
        self.anime4k_options = anime4k.preset_options()
        saved_preset = self.settings.get("anime4k")
        self.anime4k_var = tk.StringVar(
            value=saved_preset if saved_preset in self.anime4k_options else anime4k.default_preset(self.anime4k_options)
        )

        shell = tk.Frame(root, bg="#d8cdbd", padx=1, pady=1)
        shell.pack(fill="both", expand=True)
        surface = tk.Frame(shell, bg=background)
        surface.pack(fill="both", expand=True)

        titlebar = tk.Frame(surface, bg=chrome, height=42)
        if not IS_MAC:
            titlebar.pack(fill="x")
        titlebar.pack_propagate(False)
        titlebar.columnconfigure(0, weight=1)
        titlebar.columnconfigure(1, weight=0)
        titlebar.columnconfigure(2, weight=1)
        title_label = tk.Label(
            titlebar,
            text="DOKI",
            bg=chrome,
            fg="#f5f0e7",
            font=(font_family, 9, "bold"),
            padx=0,
            pady=0,
        )
        title_label.grid(row=0, column=1, sticky="nsew")
        title_label.bind("<ButtonPress-1>", self._start_window_drag)
        title_label.bind("<B1-Motion>", self._drag_window)
        controls = tk.Frame(titlebar, bg=chrome)
        controls.grid(row=0, column=2, sticky="e", padx=(0, 5))
        minimize_button = tk.Label(
            controls,
            text="—",
            bg=chrome,
            fg="#f5f0e7",
            font=(font_family, 12),
            width=4,
            cursor="hand2",
        )
        minimize_button.pack(side="left", padx=(0, 2), ipady=2)
        minimize_button.bind("<Enter>", lambda _event: minimize_button.configure(bg="#52665a"))
        minimize_button.bind("<Leave>", lambda _event: minimize_button.configure(bg=chrome))
        minimize_button.bind("<Button-1>", lambda _event: root.iconify())
        close_button = tk.Label(
            controls,
            text="×",
            bg=chrome,
            fg="#f5f0e7",
            font=(font_family, 15),
            width=4,
            cursor="hand2",
        )
        close_button.pack(side="left", ipady=1)
        close_button.bind("<Enter>", lambda _event: close_button.configure(bg="#b85c54"))
        close_button.bind("<Leave>", lambda _event: close_button.configure(bg=chrome))
        close_button.bind("<Button-1>", lambda _event: root.destroy())
        titlebar.bind("<ButtonPress-1>", self._start_window_drag)
        titlebar.bind("<B1-Motion>", self._drag_window)

        body = ttk.Frame(surface, padding=(38, 22, 38, 22), style="App.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        heading = ttk.Frame(body, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="A LITTLE COZY PLAYER FOR THE BOYS", style="Eyebrow.TLabel").grid(
            row=0, column=0, sticky="w", pady=(3, 0)
        )
        # ttk.Label(heading, text="doki", style="Title.TLabel").grid(
        #     row=1, column=0, sticky="w", pady=(4, 2)
        # )
        ttk.Label(
            heading,
            text="Settle in, pick your stream, and let mpv take it from here.",
            style="Subtitle.TLabel",
        ).grid(row=2, column=0, sticky="w")
        self.update_label = tk.Label(
            heading, text="", bg=background, fg=green, font=(font_family, 9, "bold", "underline"), cursor="hand2",
        )
        self.update_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.update_label.grid_remove()
        self.mascot_canvas = tk.Canvas(
            heading,
            width=116,
            height=132,
            bg="#f5f0e7",
            highlightthickness=0,
            borderwidth=0,
        )
        self.mascot_canvas.grid(row=0, column=1, rowspan=3, sticky="e", padx=(12, 0))
        self._mascot_frame = 0
        self._mascot_images = []
        mascot_path = resource_path("assets", "dancing-anime-girl.gif")
        if os.path.isfile(mascot_path):
            try:
                with open(mascot_path, "rb") as mascot_file:
                    image_data = base64.b64encode(mascot_file.read()).decode("ascii")
                frame_index = 0
                while True:
                    try:
                        image = tk.PhotoImage(
                            data=image_data,
                            format=f"gif -index {frame_index}",
                        )
                    except tk.TclError:
                        break
                    scale = max(1, (max(image.width(), image.height()) + 111) // 112)
                    self._mascot_images.append(image.subsample(scale, scale))
                    frame_index += 1
            except tk.TclError as error:
                print(f"[gui] Could not load dancing mascot GIF: {error}", file=sys.stderr)
            if not self._mascot_images:
                print(f"[gui] Dancing mascot GIF contains no readable frames: {mascot_path}", file=sys.stderr)
                self.mascot_canvas.create_text(
                    58, 66, text="Mascot unavailable", fill="#78847a",
                    font=(font_family, 8),
                )
        else:
            print(f"[gui] Dancing mascot GIF not found: {mascot_path}", file=sys.stderr)
            self.mascot_canvas.create_text(
                58, 66, text="Mascot unavailable", fill="#78847a",
                font=(font_family, 8),
            )
        self._animate_mascot()

        episode = ttk.LabelFrame(body, text="  Episode  ", padding=(18, 15), style="Card.TLabelframe")
        episode.grid(row=1, column=0, sticky="ew", pady=(14, 14))
        episode.columnconfigure(0, weight=1)
        ttk.Label(episode, text="Paste the episode or player link").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        self.url_entry = ttk.Entry(episode, textvariable=self.url_var, font=(font_family, 11))
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.analyze_button = ttk.Button(episode, text="Find stream", command=self.analyze)
        self.analyze_button.grid(row=1, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda _event: self.analyze())
        recents = ttk.Frame(episode, style="Card.TFrame")
        recents.grid(row=2, column=0, sticky="ew", padx=(0, 10), pady=(10, 0))
        recents.columnconfigure(0, weight=1)
        self.recent_combo = ttk.Combobox(
            recents,
            textvariable=self.recent_var,
            state="readonly",
            postcommand=lambda: self._refresh_recents(keep_selection=True),
        )
        self.recent_combo.grid(row=0, column=0, sticky="ew")
        self.recent_combo.bind("<<ComboboxSelected>>", self._select_recent)
        self.remove_recent_button = ttk.Button(recents, text="✕", width=3, command=self.remove_recent)
        self.remove_recent_button.grid(row=0, column=1, padx=(6, 0))
        self.next_button = ttk.Button(episode, text="Next episode", command=self.next_episode)
        self.next_button.grid(row=2, column=1, sticky="ew", pady=(10, 0))
        self._refresh_recents()

        self.progress = ttk.Progressbar(body, mode="indeterminate", length=100, style="Warm.Horizontal.TProgressbar")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(1, 7))
        ttk.Label(body, textvariable=self.status_var, style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 17))

        playback = ttk.LabelFrame(body, text="  Make yourself at home - IN MEMORY OF TIM BERGMAN ", padding=(18, 16), style="Card.TLabelframe")
        playback.grid(row=4, column=0, sticky="ew")
        playback.columnconfigure(0, weight=1)
        playback.columnconfigure(1, weight=1)

        ttk.Label(playback, text="Stream quality").grid(row=0, column=0, sticky="w", padx=(0, 14), pady=(0, 6))
        ttk.Label(playback, text="Subtitles").grid(row=0, column=1, sticky="w", pady=(0, 6))
        self.quality_combo = ttk.Combobox(
            playback, textvariable=self.quality_var, values=("Auto (mpv default)",), state="readonly"
        )
        self.quality_combo.grid(row=1, column=0, sticky="ew", padx=(0, 14), pady=(0, 20))
        self.subtitle_combo = ttk.Combobox(
            playback, textvariable=self.subtitle_var, values=("No subtitles",), state="readonly"
        )
        self.subtitle_combo.grid(row=1, column=1, sticky="ew", pady=(0, 20))

        ttk.Label(playback, text="Cache · seconds").grid(row=2, column=0, sticky="w", padx=(0, 14), pady=(0, 6))
        ttk.Label(playback, text="Initial buffer · seconds").grid(row=2, column=1, sticky="w", pady=(0, 6))
        self.cache_spin = ttk.Spinbox(playback, from_=5, to=1320, increment=5, textvariable=self.cache_var, width=10)
        self.cache_spin.grid(row=3, column=0, sticky="w", padx=(0, 14))
        self.buffer_spin = ttk.Spinbox(playback, from_=0, to=45, increment=1, textvariable=self.buffer_var, width=10)
        self.buffer_spin.grid(row=3, column=1, sticky="w")

        ttk.Label(playback, text="Anime4K upscaling").grid(row=4, column=0, columnspan=2, sticky="w", pady=(20, 6))
        self.anime4k_combo = ttk.Combobox(
            playback, textvariable=self.anime4k_var, values=list(self.anime4k_options), state="readonly"
        )
        self.anime4k_combo.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            playback,
            text=(
                "Auto uses Mode A+A for 1080p: best quality, but heavy on the GPU. If it stutters, "
                "pick Mode A or a Fast preset (Ctrl+1 in the player switches to Mode A)."
            ),
            style="Hint.TLabel",
            wraplength=680,
            justify="left",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        footer = ttk.Frame(body, style="App.TFrame")
        footer.grid(row=5, column=0, sticky="ew", pady=(18, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            footer,
            text="Save an mpv debug log when playing" if IS_MAC else "Show debug console when playing",
            variable=self.debug_var,
            style="Muted.TCheckbutton",
            command=self._save_debug_setting,
        ).grid(row=0, column=0, sticky="w")
        self.start_button = ttk.Button(footer, text="  Start watching  ", style="Primary.TButton", command=self.start_mpv)
        self.start_button.grid(row=0, column=1, sticky="e")
        self.start_button.state(["disabled"])

        root.after(100, self.poll_events)
        self._taskbar_registered = False
        root.after(100, self._register_custom_taskbar_button)
        self.url_entry.focus_set()
        self._prefill_from_clipboard()
        threading.Thread(target=remove_stale_subtitles, daemon=True).start()
        threading.Thread(target=lambda: self.events.put(("update", check_for_update())), daemon=True).start()

    def _show_update(self, update):
        if not update:
            return
        version, url = update
        self.update_label.configure(text=f"doki {version} is out - click to download")
        self.update_label.bind("<Button-1>", lambda _event: webbrowser.open(url))
        self.update_label.grid()

    def _save_debug_setting(self):
        self.settings["debug_console"] = self.debug_var.get()
        save_json("settings.json", self.settings)

    def _video_height(self):
        """Height of the stream mpv will play, for picking an Anime4K mode."""
        variants = parse_hls_variants(self.stream_url, self.playlist_text)
        heights = [variant["height"] for variant in variants if variant["height"]]
        bitrate = self.quality_options.get(self.quality_var.get())
        if isinstance(bitrate, int):
            chosen = [variant["height"] for variant in variants if variant["bandwidth"] == bitrate and variant["height"]]
            if chosen:
                return chosen[0]
        if heights:
            return max(heights)
        player_video_size = self.capture_result[3] if self.capture_result else None
        return player_video_size[1] if player_video_size else None

    def _anime4k_shaders(self):
        """Returns (shader list or None, short description for the status line)."""
        choice = self.anime4k_options[self.anime4k_var.get()]
        if choice != anime4k.AUTO:
            return choice, ""
        height = self._video_height()
        mode = anime4k.mode_for_height(height)
        detail = f" with Anime4K Mode {mode}" + (f" for {height}p" if height else "")
        return anime4k.shader_files(mode, "HQ"), detail

    def _prefill_from_clipboard(self):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            return
        parsed = urlsplit(text)
        if parsed.scheme in ("http", "https") and parsed.netloc and not any(char.isspace() for char in text):
            self.url_var.set(text)
            self.status_var.set("Link pasted from your clipboard. Press Find stream when ready.")

    def _refresh_recents(self, keep_selection=False):
        selected_url = self.recent_options.get(self.recent_var.get()) if keep_selection else None
        self.recent_options = {}
        for entry in self.history:
            title = entry.get("title") or urlsplit(entry["url"]).path.strip("/") or entry["url"]
            progress = watch_progress(entry["url"])
            if progress and is_finished(*progress):
                detail = "✓ watched"
            elif progress and progress[1]:
                detail = f"{format_timestamp(progress[0])} / {format_timestamp(progress[1])}"
            elif progress:
                detail = f"stopped at {format_timestamp(progress[0])}"
            else:
                detail = entry.get("watched", "")
            label = f"{title}  ·  {detail}" if detail else title
            if label in self.recent_options:
                label += f" ({len(self.recent_options)})"
            self.recent_options[label] = entry["url"]
        labels = list(self.recent_options)
        self.recent_combo.configure(values=labels)
        selected_label = next((label for label, url in self.recent_options.items() if url == selected_url), None)
        self.recent_var.set(selected_label or ("Recently watched" if labels else "No history yet"))

    def remove_recent(self):
        label = self.recent_var.get()
        page_url = self.recent_options.get(label)
        if not page_url:
            self.status_var.set("Pick an episode from Recently watched to remove it.")
            return
        self.history = remove_history_entry(page_url)
        self._refresh_recents()
        self.status_var.set(f"Removed from history: {label.split('  ·  ')[0]}")

    def _select_recent(self, _event=None):
        page_url = self.recent_options.get(self.recent_var.get())
        if page_url:
            self.url_var.set(page_url)
            self.url_entry.icursor("end")

    def next_episode(self):
        page_url = self.url_var.get().strip()
        next_url = next_episode_url(page_url) if page_url else None
        if not next_url:
            messagebox.showinfo(
                "Next episode",
                "Couldn't find an episode number in this link. Paste the next episode's link instead.",
                parent=self.root,
            )
            return
        self.url_var.set(next_url)
        self.analyze()

    def _register_custom_taskbar_button(self):
        if os.name != "nt" or self._taskbar_registered:
            return

        self.root.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
        if not hwnd:
            raise ctypes.WinError()

        get_window_long = user32.GetWindowLongPtrW
        get_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int)
        get_window_long.restype = ctypes.c_ssize_t
        set_window_long = user32.SetWindowLongPtrW
        set_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
        set_window_long.restype = ctypes.c_ssize_t

        ex_style_index = -20
        app_window = 0x00040000
        tool_window = 0x00000080
        extended_style = get_window_long(hwnd, ex_style_index)
        ctypes.set_last_error(0)
        set_window_long(hwnd, ex_style_index, (extended_style | app_window) & ~tool_window)
        if ctypes.get_last_error():
            raise ctypes.WinError()

        set_window_pos = user32.SetWindowPos
        set_window_pos.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        )
        set_window_pos.restype = ctypes.c_int
        if not set_window_pos(hwnd, None, 0, 0, 0, 0, 0x0037):
            raise ctypes.WinError()

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        ole32 = ctypes.windll.ole32
        ole32.CLSIDFromString.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(GUID))
        ole32.CLSIDFromString.restype = ctypes.c_long

        def parse_guid(value):
            parsed = GUID()
            result = ole32.CLSIDFromString(value, ctypes.byref(parsed))
            if result < 0:
                raise OSError(f"Invalid Windows taskbar interface GUID: {value}")
            return parsed

        ole32.CoInitialize.argtypes = (ctypes.c_void_p,)
        ole32.CoInitialize.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = ()
        ole32.CoUninitialize.restype = None
        init_result = ole32.CoInitialize(None)
        changed_mode = ctypes.c_uint32(init_result).value == 0x80010106
        if init_result < 0 and not changed_mode:
            raise OSError(
                f"COM initialization failed: 0x{ctypes.c_uint32(init_result).value:08X}"
            )

        taskbar_list = ctypes.c_void_p()
        try:
            taskbar_class = parse_guid("{56FDF344-FD6D-11D0-958A-006097C9A090}")
            taskbar_interface = parse_guid("{56FDF342-FD6D-11D0-958A-006097C9A090}")
            ole32.CoCreateInstance.argtypes = (
                ctypes.POINTER(GUID),
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )
            ole32.CoCreateInstance.restype = ctypes.c_long
            result = ole32.CoCreateInstance(
                ctypes.byref(taskbar_class),
                None,
                1,
                ctypes.byref(taskbar_interface),
                ctypes.byref(taskbar_list),
            )
            if result < 0:
                raise OSError(
                    f"Could not create Windows taskbar interface: "
                    f"0x{ctypes.c_uint32(result).value:08X}"
                )

            vtable = ctypes.cast(
                taskbar_list,
                ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
            ).contents
            initialize = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])
            add_tab = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_void_p,
            )(vtable[4])
            result = initialize(taskbar_list)
            if result < 0:
                raise OSError(
                    f"Could not initialize Windows taskbar interface: "
                    f"0x{ctypes.c_uint32(result).value:08X}"
                )
            result = add_tab(taskbar_list, ctypes.c_void_p(hwnd))
            if result < 0:
                raise OSError(
                    f"Could not register the app with the taskbar: "
                    f"0x{ctypes.c_uint32(result).value:08X}"
                )
            self._taskbar_registered = True
            print("[gui] Registered the custom-title-bar window with the Windows taskbar.")
        finally:
            if taskbar_list.value:
                vtable = ctypes.cast(
                    taskbar_list,
                    ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
                ).contents
                release = ctypes.WINFUNCTYPE(
                    ctypes.c_ulong,
                    ctypes.c_void_p,
                )(vtable[2])
                release(taskbar_list)
            if not changed_mode and init_result >= 0:
                ole32.CoUninitialize()

    def _start_window_drag(self, event):
        self._window_drag_offset_x = event.x_root - self.root.winfo_x()
        self._window_drag_offset_y = event.y_root - self.root.winfo_y()

    def _drag_window(self, event):
        x = event.x_root - self._window_drag_offset_x
        y = event.y_root - self._window_drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _animate_mascot(self):
        if self._mascot_images:
            image = self._mascot_images[self._mascot_frame % len(self._mascot_images)]
            self.mascot_canvas.delete("all")
            self.mascot_canvas.create_image(58, 66, image=image)
            self._mascot_frame += 1
        self.root.after(80, self._animate_mascot)

    def analyze(self):
        page_url = self.url_var.get().strip()
        parsed = urlsplit(page_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            messagebox.showerror("Invalid URL", "Enter a complete http or https episode URL.", parent=self.root)
            return

        self.capture_result = None
        self.page_title = ""
        self.start_button.state(["disabled"])
        self.analyze_button.state(["disabled"])
        self.next_button.state(["disabled"])
        self.status_var.set("Opening the page in a browser...")
        self.progress.start(12)
        threading.Thread(target=self.capture_worker, args=(page_url,), daemon=True).start()

    def capture_worker(self, page_url):
        try:
            page_info = {}
            result = capture_page(page_url, lambda text: self.events.put(("status", text)), page_info)
        except Exception as error:
            self.events.put(("error", str(error)))
        else:
            self.events.put(("result", (result, page_info.get("title", ""))))

    def poll_events(self):
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "status":
                self.status_var.set(payload)
            elif event == "update":
                self._show_update(payload)
            elif event == "error":
                self.progress.stop()
                self.analyze_button.state(["!disabled"])
                self.next_button.state(["!disabled"])
                self.status_var.set("Capture failed")
                messagebox.showerror("Browser capture failed", payload, parent=self.root)
            else:
                self.finish_capture(payload)
        self.root.after(100, self.poll_events)

    def finish_capture(self, payload):
        result, self.page_title = payload
        self.progress.stop()
        self.analyze_button.state(["!disabled"])
        self.next_button.state(["!disabled"])
        streams, subtitle_candidates, subtitle_responses, player_video_size = result
        if not streams:
            self.status_var.set("No HLS stream found. Try again and press Play in the browser if needed.")
            return

        self.capture_result = result
        self.stream_url, self.headers, self.playlist_text, response_status, content_type = max(
            streams,
            key=lambda item: ("#EXT-X-STREAM-INF:" in item[2], len(item[2])),
        )
        hls_tracks = parse_hls_subtitle_tracks(self.stream_url, self.playlist_text)

        self.quality_options = dict(make_quality_options(self.stream_url, self.playlist_text))
        quality_labels = list(self.quality_options)
        self.quality_combo.configure(values=quality_labels)
        preferred_quality = self.settings.get("quality")
        self.quality_var.set(preferred_quality if preferred_quality in quality_labels else quality_labels[0])

        subtitle_choices = make_subtitle_options(subtitle_candidates, hls_tracks)
        self.subtitle_options = {label: selection for label, selection in subtitle_choices}
        self.subtitle_combo.configure(values=list(self.subtitle_options))
        preferred_subtitle = None
        if self.settings.get("subtitles") != "none":
            preferred_subtitle = (
                preferred_subtitle_label(subtitle_choices, self.settings.get("subtitle_language", "en"))
                or preferred_subtitle_label(subtitle_choices, "en")
            )
        self.subtitle_var.set(preferred_subtitle or "No subtitles")
        subtitle_languages = sorted({
            language_name(selection["language"])
            for selection in self.subtitle_options.values()
            if selection["kind"] != "none" and selection["language"]
        })

        variant_count = len(parse_hls_variants(self.stream_url, self.playlist_text))
        detail = f"HTTP {response_status} {content_type or ''}".strip()
        if variant_count:
            detail += f" - {variant_count} quality options"
        if player_video_size and player_video_size[0] and player_video_size[1]:
            detail += f" - detected {player_video_size[0]}x{player_video_size[1]}"
        if subtitle_languages:
            detail += " - subtitles: " + ", ".join(subtitle_languages)
        self.status_var.set(f"Stream ready: {detail}")
        self.start_button.state(["!disabled"])

    def start_mpv(self):
        if not self.capture_result or not self.stream_url:
            return
        mpv_executable = find_mpv_executable()
        if not mpv_executable:
            messagebox.showerror(
                "mpv is required",
                "Install mpv (for example with `brew install mpv`) before starting playback."
                if IS_MAC
                else "Install mpv, then add mpv.exe to PATH or register it with Windows before starting playback.",
                parent=self.root,
            )
            return
        try:
            cache_secs = int(self.cache_var.get())
            initial_buffer = int(self.buffer_var.get())
            if not 5 <= cache_secs <= 1320 or not 0 <= initial_buffer <= 45:
                raise ValueError("Cache must be 5-1320 seconds and initial buffer 0-45 seconds.")
        except ValueError as error:
            messagebox.showerror("Invalid buffering options", str(error), parent=self.root)
            return

        page_url = self.url_var.get().strip()
        start_position = read_resume_position(page_url)
        if start_position and not messagebox.askyesno(
            "Resume?",
            f"You stopped at {format_timestamp(start_position)} last time. Resume from there?",
            parent=self.root,
        ):
            start_position = None
        extra_args = make_resume_arguments(page_url, self.page_title, start_position)
        shaders, anime4k_detail = self._anime4k_shaders()
        extra_args += anime4k.shader_arguments(shaders)
        debug = self.debug_var.get()

        selection = self.subtitle_options[self.subtitle_var.get()]
        self.settings.update({
            "cache_secs": cache_secs,
            "initial_buffer": initial_buffer,
            "quality": self.quality_var.get(),
            "subtitles": "none" if selection["kind"] == "none" else "auto",
            "subtitle_language": selection["language"] or self.settings.get("subtitle_language", "en"),
            "anime4k": self.anime4k_var.get(),
        })
        save_json("settings.json", self.settings)
        subtitle_urls = ()
        cleanup_paths = []
        subtitles_enabled = selection["kind"] != "none"
        subtitle_languages = selection.get("slang") or ["en"]
        subtitle_track = selection["sid"] if selection["kind"] == "playlist" and not selection["language"] else None
        if selection["kind"] == "external":
            subtitle_url = selection["url"]
            _, _, subtitle_responses, _ = self.capture_result
            local_file = save_captured_subtitle(subtitle_url, subtitle_responses.get(subtitle_url))
            subtitle_urls = (local_file or subtitle_url,)
            if local_file:
                cleanup_paths.append(local_file)

        command = make_mpv_command(
            self.stream_url,
            self.headers,
            self.url_var.get().strip(),
            subtitle_urls,
            mpv_executable,
            bitrate=self.quality_options[self.quality_var.get()],
            cache_secs=cache_secs,
            initial_buffer=initial_buffer,
            subtitles_enabled=subtitles_enabled,
            extra_args=extra_args,
            debug=debug,
            subtitle_languages=subtitle_languages,
            subtitle_track=subtitle_track,
        )
        launch_executable, launch_arguments = make_mpv_arguments(
            self.stream_url,
            self.headers,
            self.url_var.get().strip(),
            subtitle_urls,
            mpv_executable,
            bitrate=self.quality_options[self.quality_var.get()],
            cache_secs=cache_secs,
            initial_buffer=initial_buffer,
            subtitles_enabled=subtitles_enabled,
            extra_args=extra_args,
            debug=debug,
            subtitle_languages=subtitle_languages,
            subtitle_track=subtitle_track,
        )
        _, subtitle_candidates, _, _ = self.capture_result
        hls_tracks = parse_hls_subtitle_tracks(self.stream_url, self.playlist_text)
        debug_messages = [
            f"[subtitle-debug] selected source: {selection['kind']} ({language_name(selection['language'])})",
            f"[subtitle-debug] HLS subtitle tracks detected: {len(hls_tracks)}",
            f"[subtitle-debug] external subtitle candidates detected: {len(subtitle_candidates)}",
            f"[subtitle-debug] subtitles enabled: {'yes' if subtitles_enabled else 'no'}",
        ]
        if selection["kind"] == "external":
            debug_messages.append(
                "[subtitle-debug] external subtitle supplied from "
                + ("a captured local file" if cleanup_paths else "its original URL")
            )
        debug_detail = " with a debug console."
        try:
            if debug and IS_MAC:
                log_path = data_path("mpv-debug.log")
                launch_mpv(launch_executable, launch_arguments + [f"--log-file={log_path}"], cleanup_paths)
                debug_detail = f". Debug log: {log_path}"
            elif not debug:
                launch_mpv(launch_executable, launch_arguments, cleanup_paths)
            elif not launch_in_new_powershell(
                command,
                cleanup_paths,
                debug_messages,
                launch_executable,
                launch_arguments,
            ):
                raise OSError("Could not open PowerShell. Check that PowerShell is installed.")
        except OSError as error:
            messagebox.showerror("Could not start mpv", str(error), parent=self.root)
            return
        self.history = add_history_entry(page_url, self.page_title)
        self._refresh_recents()
        self.status_var.set(
            f"Started mpv{anime4k_detail}" + (debug_detail if debug else ". Enjoy!")
        )


def main():
    root = tk.Tk()
    M3u8App(root)
    root.mainloop()
