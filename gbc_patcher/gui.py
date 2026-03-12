"""
gui.py
------
Tkinter-based GUI for the GBC Cheat Tool.

Layout
------
┌──────────────────────────────────────────────────────┐
│  menu bar  (File)                                    │
├────────────────────────┬─────────────────────────────┤
│                        │  CHEATS                     │
│   Game Display         │  🛡 Invincibility            │
│   (160×144 × 3)        │  💰 Red Team money           │
│                        │  💰 White Team money         │
├────────────────────────┴─────────────────────────────┤
│  [⏸ Pause]  Speed: [1×][2×][4×][MAX]  FPS  [✕ Close]│
└──────────────────────────────────────────────────────┘

Dependencies
------------
  pip install pyboy pillow
"""

import logging
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Optional


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme / palette
# ---------------------------------------------------------------------------
DARK_BG       = "#1a1a2e"
PANEL_BG      = "#16213e"
CARD_BG       = "#0f3460"
CARD_HOVER    = "#1a4a7a"
ACCENT        = "#e94560"
ACCENT_DIM    = "#a02040"
TEXT_PRIMARY  = "#eaeaea"
TEXT_DIM      = "#8899aa"
TEXT_FIRED    = "#4ade80"
TEXT_WAITING  = "#facc15"
TEXT_DISABLED = "#555577"
BORDER        = "#2a3a5a"

GBC_W, GBC_H = 160, 144
SCALE        = 3
CANVAS_W     = GBC_W * SCALE
CANVAS_H     = GBC_H * SCALE
PANEL_W      = 280
FRAME_MS     = 16

# ---------------------------------------------------------------------------
# Keyboard → PyBoy button mapping
# ---------------------------------------------------------------------------
KEY_MAP = {
    "Up":        "up",
    "Down":      "down",
    "Left":      "left",
    "Right":     "right",
    "x":         "a",
    "y":         "b",
    "Return":    "start",
    "BackSpace": "select",
    "w":         "up",
    "s":         "down",
    "a":         "left",
    "d":         "right",
}

# ---------------------------------------------------------------------------
# InvincibilityManager
# ---------------------------------------------------------------------------

_RED_HP_ADDRS   = frozenset(0xC988 + i * 0x10 for i in range(41))
_WHITE_HP_ADDRS = frozenset(0xCC18 + i * 0x10 for i in range(41))

_INVINC_HOOK_BANK = 0
_INVINC_HOOK_ADDR = 0x3A81

_TURN_ADDR        = 0xC4D3   # 1 = Red's turn, 0 = White's turn
_HOOK_BANK        = 4

_HOOK_ADDR_A      = 0x6190   # Load 0xC60C into A under matching-team invincibility
_HOOK_ADDR_B      = 0x6199   # Load 0xC614 into A under opposing-team invincibility

_RAM_LOAD_ADDR_A  = 0xC60C
_RAM_LOAD_ADDR_B  = 0xC614

class InvincibilityManager:
    """
    Manages three hooks to implement per-team invincibility.

    Hook 1 — bank=0 0x3A81 (LD [DE], A — HP write-back):
        If DE points at a unit of an invincible team, A is replaced with
        the current HP value so the write becomes a no-op.

    Hook 2 — bank=13 0x6190:
        If the active team is invincible (red's turn + red invincible, or
        white's turn + white invincible), loads RAM[0xC60C] into A.

    Hook 3 — bank=13 0x6199:
        If the *opposing* team is invincible (red's turn + white invincible,
        or white's turn + red invincible), loads RAM[0xC614] into A.
    """

    def __init__(self):
        self.red_invincible:   bool = False
        self.white_invincible: bool = False
        self._registered:      bool = False
        self._pyboy                  = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, pyboy) -> None:
        if self._registered:
            return
        self._pyboy = pyboy

        pyboy.hook_register(
            _INVINC_HOOK_BANK,
            _INVINC_HOOK_ADDR,
            self._callback,
            context=pyboy.register_file,
        )
        logger.info(
            "Invincibility hook registered at bank=%d addr=0x%04X",
            _INVINC_HOOK_BANK, _INVINC_HOOK_ADDR,
        )

        pyboy.hook_register(
            _HOOK_BANK,
            _HOOK_ADDR_A,
            self._callback_6190,
            context=pyboy.register_file,
        )
        logger.info(
            "Invincibility hook registered at bank=%d addr=0x%04X",
            _HOOK_BANK, _HOOK_ADDR_A,
        )

        pyboy.hook_register(
            _HOOK_BANK,
            _HOOK_ADDR_B,
            self._callback_6199,
            context=pyboy.register_file,
        )
        logger.info(
            "Invincibility hook registered at bank=%d addr=0x%04X",
            _HOOK_BANK, _HOOK_ADDR_B,
        )

        self._registered = True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_red_turn(self) -> bool:
        """Returns True when 0xC4D3 == 0 (Red's turn)."""
        return self._pyboy.memory[_TURN_ADDR] == 0

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _callback(self, register_file) -> None:
        """Hook 1 — suppress HP write-back for invincible units."""
        if self._pyboy is None:
            return
        de = (register_file.D << 8) | register_file.E
        if de in _RED_HP_ADDRS and self.red_invincible:
            register_file.A = self._pyboy.memory[de]
            logger.debug("Invincibility: blocked Red HP write DE=0x%04X", de)
        elif de in _WHITE_HP_ADDRS and self.white_invincible:
            register_file.A = self._pyboy.memory[de]
            logger.debug("Invincibility: blocked White HP write DE=0x%04X", de)

    def _callback_6190(self, register_file) -> None:
        """
        Hook 2 — active-team invincibility.
        Fires at bank=13 0x6190.
        Loads RAM[0xC60C] into A when the team whose turn it is is invincible.
        """
        if self._pyboy is None:
            return
        red_turn = self._is_red_turn()
        if (red_turn and self.red_invincible) or (not red_turn and self.white_invincible):
            register_file.A = self._pyboy.memory[_RAM_LOAD_ADDR_A]
            logger.debug(
                "Hook 0x6190: loaded RAM[0x%04X]=0x%02X into A (red_turn=%s)",
                _RAM_LOAD_ADDR_A, register_file.A, red_turn,
            )

    def _callback_6199(self, register_file) -> None:
        """
        Hook 3 — opposing-team invincibility.
        Fires at bank=13 0x6199.
        Loads RAM[0xC614] into A when the team *not* taking its turn is invincible.
        """
        if self._pyboy is None:
            return
        red_turn = self._is_red_turn()
        if (red_turn and self.white_invincible) or (not red_turn and self.red_invincible):
            register_file.A = self._pyboy.memory[_RAM_LOAD_ADDR_B]
            logger.debug(
                "Hook 0x6199: loaded RAM[0x%04X]=0x%02X into A (red_turn=%s)",
                _RAM_LOAD_ADDR_B, register_file.A, red_turn,
            )

# ---------------------------------------------------------------------------
# InvincibilityCard widget
# ---------------------------------------------------------------------------

class InvincibilityCard(tk.Frame):
    """Per-team invincibility toggle card."""

    def __init__(self, parent, manager: InvincibilityManager, **kwargs):
        super().__init__(parent, bg=CARD_BG, **kwargs)
        self._mgr       = manager
        self._red_var   = tk.BooleanVar(value=False)
        self._white_var = tk.BooleanVar(value=False)
        self._build()

    def _build(self):
        self.config(pady=8, padx=10)

        hdr = tk.Frame(self, bg=CARD_BG)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="🛡  Invincibility",
            font=("Segoe UI", 10, "bold"),
            bg=CARD_BG, fg="#a78bfa",
        ).pack(side="left")

        btn_row = tk.Frame(self, bg=CARD_BG)
        btn_row.pack(fill="x", pady=(8, 0))
        for label, var, color, attr in [
            ("Red Team",   self._red_var,   "#e94560", "red_invincible"),
            ("White Team", self._white_var, "#aabbdd", "white_invincible"),
        ]:
            self._make_toggle(btn_row, label, var, color, attr)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(8, 0))

    def _make_toggle(self, parent, label, var, color, attr):
        frame = tk.Frame(parent, bg=CARD_BG)
        frame.pack(side="left", padx=(0, 8))

        def _toggle():
            state = var.get()
            setattr(self._mgr, attr, state)
            btn.config(
                text=f"● {label}" if state else f"○ {label}",
                bg="#1a2a1a" if state else CARD_BG,
                fg=color if state else TEXT_DISABLED,
            )
            logger.info("Invincibility %s: %s", label, "ON" if state else "OFF")

        btn = tk.Checkbutton(
            frame, text=f"○ {label}",
            variable=var, command=_toggle,
            font=("Segoe UI", 9, "bold"),
            bg=CARD_BG, fg=TEXT_DISABLED,
            activebackground=CARD_BG, activeforeground=color,
            selectcolor=DARK_BG, indicatoron=False,
            relief="flat", padx=10, pady=5, cursor="hand2",
        )
        btn.pack()


# ---------------------------------------------------------------------------
# TeamMoneyCard widget
# ---------------------------------------------------------------------------

class TeamMoneyCard(tk.Frame):
    """
    Interactive money editor for one team.

    Memory layout — 16-bit little-endian:
      value = hi_byte * 65,536 + mi_byte * 256 + lo_byte   (max 99,999)

      Red  : lo=0xFFE6  mi=0xFFE7  hi=0xFFE8
      White: lo=0xFFE9  mi=0xFFEA  hi=0xFFEB
      
      hi_byte can either be 00 or 01

    Example: FFE9=0xF0, FFEA=0x55 → 0x55*256 + 0xF0 = 22,000
    """

    MAX_VAL = 99_999
    PRESETS = [
        ("+1K",   +1_000),
        ("+5K",   +5_000),
        ("+10K", +10_000),
        ("-1K",   -1_000),
        ("-5K",   -5_000),
        ("-10K", -10_000),
    ]

    def __init__(self, parent, team_name: str, color: str,
                 addr_lo: int, addr_mi: int, addr_hi: int, get_emulator, **kwargs):
        super().__init__(parent, bg=CARD_BG, **kwargs)
        self._team    = team_name
        self._color   = color
        self._addr_lo = addr_lo
        self._addr_mi = addr_mi
        self._addr_hi = addr_hi
        self._get_emu = get_emulator
        self._mode    = tk.StringVar(value="add")
        self._build()

    def _build(self):
        self.config(pady=8, padx=10)

        hdr = tk.Frame(self, bg=CARD_BG)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text=f"💰  {self._team} Team",
            font=("Segoe UI", 10, "bold"),
            bg=CARD_BG, fg=self._color,
        ).pack(side="left")
        self._current_lbl = tk.Label(
            hdr, text="$—",
            font=("Courier", 10, "bold"),
            bg=CARD_BG, fg=TEXT_PRIMARY,
        )
        self._current_lbl.pack(side="right")

        presets_row = tk.Frame(self, bg=CARD_BG)
        presets_row.pack(fill="x", pady=(6, 0))
        for label, delta in self.PRESETS:
            pos = delta > 0
            tk.Button(
                presets_row, text=label,
                font=("Segoe UI", 8, "bold"),
                bg="#1a3a20" if pos else "#3a1a20",
                fg=TEXT_FIRED if pos else ACCENT,
                activebackground="#2a5a30" if pos else "#5a2a30",
                activeforeground=TEXT_FIRED if pos else ACCENT,
                relief="flat", padx=4, pady=2, cursor="hand2",
                command=lambda d=delta: self._apply_delta(d),
            ).pack(side="left", padx=2)

        inp_row = tk.Frame(self, bg=CARD_BG)
        inp_row.pack(fill="x", pady=(6, 0))

        mode_frame = tk.Frame(inp_row, bg=CARD_BG)
        mode_frame.pack(side="left", padx=(0, 6))
        for text, val in [("±Add", "add"), ("=Set", "set")]:
            tk.Radiobutton(
                mode_frame, text=text, variable=self._mode, value=val,
                font=("Segoe UI", 8),
                bg=CARD_BG, fg=TEXT_DIM,
                selectcolor=DARK_BG,
                activebackground=CARD_BG, activeforeground=TEXT_PRIMARY,
                indicatoron=False, relief="flat", padx=5, pady=2, cursor="hand2",
            ).pack(side="left", padx=1)

        vcmd = (self.register(self._validate_input), "%P")
        self._entry = tk.Entry(
            inp_row,
            font=("Segoe UI", 10),
            bg=DARK_BG, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat", bd=4,
            validate="key", validatecommand=vcmd,
            width=8,
        )
        self._entry.insert(0, "0")
        self._entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._entry.bind("<Return>", lambda _e: self._apply_custom())

        tk.Button(
            inp_row, text="Apply",
            font=("Segoe UI", 9, "bold"),
            bg=self._color, fg="white",
            activebackground=ACCENT_DIM, activeforeground="white",
            relief="flat", padx=8, pady=3, cursor="hand2",
            command=self._apply_custom,
        ).pack(side="right")

        self._feedback_lbl = tk.Label(
            self, text=f"  Max: {self.MAX_VAL:,}",
            font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_DIM, anchor="w",
        )
        self._feedback_lbl.pack(fill="x", pady=(4, 0))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(8, 0))

    def _read(self, pyboy) -> int:
        lo = pyboy.memory[self._addr_lo]
        mi = pyboy.memory[self._addr_mi]
        hi = pyboy.memory[self._addr_hi]
        return hi * 65_536 + mi * 256 + lo

    def _write(self, pyboy, value: int) -> int:
        value = max(0, min(value, self.MAX_VAL))
        pyboy.memory[self._addr_lo] = value & 0xFF
        pyboy.memory[self._addr_mi] = (value >> 8) & 0xFF
        pyboy.memory[self._addr_hi] = (value >> 16) & 0xFF
        return value

    def _apply_delta(self, delta: int):
        emu = self._get_emu()
        if not emu or not emu._pyboy:
            self._feedback("No game running", TEXT_WAITING)
            return
        current = self._read(emu._pyboy)
        result  = self._write(emu._pyboy, current + delta)
        sign    = "+" if delta >= 0 else ""
        self._feedback(
            f"✓  {current:,} {sign}{delta:,} = {result:,}  (0x{result:04X})",
            TEXT_FIRED,
        )

    def _apply_custom(self):
        emu = self._get_emu()
        if not emu or not emu._pyboy:
            self._feedback("No game running", TEXT_WAITING)
            return
        raw = self._entry.get().strip()
        if not raw:
            self._feedback("Enter a value first", TEXT_WAITING)
            return
        amount  = int(raw)
        current = self._read(emu._pyboy)
        if self._mode.get() == "set":
            result = self._write(emu._pyboy, amount)
            self._feedback(f"✓  Set to {result:,}  (0x{result:04X})", TEXT_FIRED)
        else:
            result = self._write(emu._pyboy, current + amount)
            self._feedback(
                f"✓  {current:,} + {amount:,} = {result:,}  (0x{result:04X})",
                TEXT_FIRED,
            )

    def _validate_input(self, new_value: str) -> bool:
        return new_value == "" or (new_value.isdigit() and len(new_value) <= 5)

    def _feedback(self, msg: str, color: str):
        self._feedback_lbl.config(text=f"  {msg}", fg=color)

    def refresh_current(self):
        emu = self._get_emu()
        if emu and emu._pyboy:
            try:
                val = self._read(emu._pyboy)
                self._current_lbl.config(text=f"${val:,}")
            except Exception:
                pass

    
# ---------------------------------------------------------------------------
# MoneyLockManager
# ---------------------------------------------------------------------------

_MONEY_HOOK_BANK = 0
_MONEY_SUB_ADDRS = (0x750B, 0x750E, 0x7511)

_RED_MONEY  = (0xFFE6, 0xFFE7, 0xFFE8)
_WHITE_MONEY = (0xFFE9, 0xFFEA, 0xFFEB)


class MoneyLockManager:
    """
    Manages the “Free Money” cheat by monitoring and correcting the in-RAM
    money values for both teams.

    The Game Boy game stores the current money values in HRAM as a 3-byte
    little-endian integer per team:

        Red team:   FFE6, FFE7, FFE8
        White team: FFE9, FFEA, FFEB

    Instead of patching the game's subtraction routine (which would affect
    both the player and the CPU), this manager observes the money values
    once per frame and restores them if they decrease while the cheat is
    enabled.

    Mechanism
    ---------
    For each team the manager stores the last known money value. During each
    update:

        1. The current money value is read from HRAM.
        2. If the cheat is active and the value decreased since the last
        frame, the previous value is written back.
        3. Otherwise the stored reference value is updated.

    This effectively prevents money from decreasing while still allowing
    normal increases (income, bonuses, etc.).
    """
    def __init__(self):
        self.red_free_money = False
        self.white_free_money = False
        self._pyboy = None
        self._last_red = 0
        self._last_white = 0

    def register(self, pyboy):
        self._pyboy = pyboy
        self._last_red = self._read_money(_RED_MONEY)
        self._last_white = self._read_money(_WHITE_MONEY)

    def protect(self):
        if not self._pyboy:
            return

        current_red = self._read_money(_RED_MONEY)
        if self.red_free_money:
            if current_red < self._last_red:
                self._write_money(_RED_MONEY, self._last_red)
                current_red = self._last_red
        self._last_red = current_red

        current_white = self._read_money(_WHITE_MONEY)
        if self.white_free_money:
            if current_white < self._last_white:
                self._write_money(_WHITE_MONEY, self._last_white)
                current_white = self._last_white
        self._last_white = current_white

    def _read_money(self, addrs):
        lo, mi, hi = addrs
        m = self._pyboy.memory
        return m[lo] | (m[mi] << 8) | (m[hi] << 16)

    def _write_money(self, addrs, value):
        lo, mi, hi = addrs
        m = self._pyboy.memory
        m[lo] = value & 0xFF
        m[mi] = (value >> 8) & 0xFF
        m[hi] = (value >> 16) & 0xFF

# ---------------------------------------------------------------------------
# MoneyLockCard widget
# ---------------------------------------------------------------------------

class MoneyLockCard(tk.Frame):
    """Per-team MoneyLock toggle card."""

    def __init__(self, parent, manager: MoneyLockManager, **kwargs):
        super().__init__(parent, bg=CARD_BG, **kwargs)
        self._mgr       = manager
        self._red_var   = tk.BooleanVar(value=False)
        self._white_var = tk.BooleanVar(value=False)
        self._build()

    def _build(self):
        self.config(pady=8, padx=10)

        hdr = tk.Frame(self, bg=CARD_BG)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="💰  MoneyLocking",
            font=("Segoe UI", 10, "bold"),
            bg=CARD_BG, fg="#a78bfa",
        ).pack(side="left")

        btn_row = tk.Frame(self, bg=CARD_BG)
        btn_row.pack(fill="x", pady=(8, 0))
        for label, var, color, attr in [
            ("Red Free Money", self._red_var, "#e94560", "red_free_money"),
            ("White Free Money", self._white_var, "#aabbdd", "white_free_money"),
        ]:
            self._make_toggle(btn_row, label, var, color, attr)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(8, 0))

    def _make_toggle(self, parent, label, var, color, attr):
        frame = tk.Frame(parent, bg=CARD_BG)
        frame.pack(side="left", padx=(0, 8))

        def _toggle():
            state = var.get()
            setattr(self._mgr, attr, state)
            btn.config(
                text=f"● {label}" if state else f"○ {label}",
                bg="#1a2a1a" if state else CARD_BG,
                fg=color if state else TEXT_DISABLED,
            )
            logger.info("MoneyLock %s: %s", label, "ON" if state else "OFF")

        btn = tk.Checkbutton(
            frame, text=f"○ {label}",
            variable=var, command=_toggle,
            font=("Segoe UI", 9, "bold"),
            bg=CARD_BG, fg=TEXT_DISABLED,
            activebackground=CARD_BG, activeforeground=color,
            selectcolor=DARK_BG, indicatoron=False,
            relief="flat", padx=10, pady=5, cursor="hand2",
        )
        btn.pack()


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class GBCPatcherApp(tk.Tk):
    """
    Main application window.

    Parameters
    ----------
    rom_path      : optional path to .gbc ROM (can also be opened via File menu)
    initial_speed : emulation speed multiplier (1=normal, 0=unlimited)
    """

    def __init__(
        self,
        rom_path: Optional[str | Path] = None,
        initial_speed: int = 1,
    ):
        super().__init__()

        self._rom_path  = Path(rom_path) if rom_path else None
        self._emulator  = None
        self._speed     = initial_speed
        self._paused    = False

        self._team_cards: list            = []
        self._team_cards_visible          = False
        self._invinc_manager              = InvincibilityManager()
        self._invinc_card: Optional[InvincibilityCard] = None
        self._invinc_card_visible         = False

        self._money_manager = MoneyLockManager()

        self._fps_frames  = 0
        self._fps_last    = time.perf_counter()
        self._fps_display = 0.0

        self._build_window()
        self._build_menu()
        self._build_layout()
        self._apply_theme()
        self._bind_keys()

        if self._rom_path:
            self.after(100, self._launch_emulator)

    # -----------------------------------------------------------------------
    # Window scaffolding
    # -----------------------------------------------------------------------

    def _build_window(self):
        self.title("GBC Cheat Tool")
        self.resizable(False, False)
        self.configure(bg=DARK_BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_menu(self):
        menubar = tk.Menu(
            self, bg=PANEL_BG, fg=TEXT_PRIMARY,
            activebackground=ACCENT, activeforeground="white", relief="flat",
        )
        file_menu = tk.Menu(
            menubar, tearoff=0, bg=PANEL_BG, fg=TEXT_PRIMARY,
            activebackground=ACCENT, activeforeground="white",
        )
        file_menu.add_command(label="Open ROM …", command=self._open_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Quit",        command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

    def _build_layout(self):
        outer = tk.Frame(self, bg=DARK_BG)
        outer.pack(fill="both", expand=True)

        # game canvas
        self._canvas = tk.Canvas(
            outer, width=CANVAS_W, height=CANVAS_H,
            bg="black", bd=0, highlightthickness=2, highlightbackground=BORDER,
        )
        self._canvas.pack(side="left", padx=(10, 6), pady=10)
        self._canvas.create_text(
            CANVAS_W // 2, CANVAS_H // 2,
            text="No ROM loaded\n\nFile → Open ROM …",
            fill=TEXT_DIM, font=("Segoe UI", 13),
            justify="center", tags="placeholder",
        )

        # right panel
        right = tk.Frame(outer, bg=PANEL_BG, width=PANEL_W)
        right.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=10)
        right.pack_propagate(False)

        tk.Label(
            right, text="CHEATS",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL_BG, fg=ACCENT,
        ).pack(anchor="w", padx=8, pady=(8, 4))
        tk.Frame(right, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(0, 6))

        # scrollable list
        list_frame = tk.Frame(right, bg=PANEL_BG)
        list_frame.pack(fill="both", expand=True, padx=6)

        scrollbar = tk.Scrollbar(
            list_frame, orient="vertical",
            bg=PANEL_BG, troughcolor=DARK_BG, activebackground=ACCENT,
        )
        scrollbar.pack(side="right", fill="y")

        self._patch_canvas = tk.Canvas(
            list_frame, bg=PANEL_BG, bd=0,
            highlightthickness=0, yscrollcommand=scrollbar.set,
        )
        self._patch_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._patch_canvas.yview)

        self._patch_list_frame = tk.Frame(self._patch_canvas, bg=PANEL_BG)
        self._patch_canvas_window = self._patch_canvas.create_window(
            (0, 0), window=self._patch_list_frame, anchor="nw",
        )
        self._patch_list_frame.bind("<Configure>", self._on_patch_list_resize)
        self._patch_canvas.bind("<Configure>", self._on_patch_canvas_resize)
        self._patch_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Invincibility card
        self._invinc_card = InvincibilityCard(
            self._patch_list_frame, manager=self._invinc_manager,
        )

        self._money_lock_card = MoneyLockCard(
            self._patch_list_frame, self._money_manager
        )
        if not self._invinc_card_visible:
            self._invinc_card.pack(fill="x", padx=4, pady=(4, 2))
            self._invinc_card_visible = True

            self._money_lock_card.pack(fill="x", padx=4, pady=(4, 2))
        
        # Money cards
        get_emu = lambda: self._emulator
        self._team_cards = [
            TeamMoneyCard(
                self._patch_list_frame,
                team_name="Red",   color="#e94560",
                addr_lo=0xFFE6,    addr_mi=0xFFE7,  addr_hi=0xFFE8,
                get_emulator=get_emu,
            ),
            TeamMoneyCard(
                self._patch_list_frame,
                team_name="White", color="#aabbdd",
                addr_lo=0xFFE9,    addr_mi=0xFFEA,  addr_hi=0xFFEB,
                get_emulator=get_emu,
            ),
        ]

        self._build_controls()

    def _build_controls(self):
        bar = tk.Frame(self, bg=PANEL_BG, height=48)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        tk.Frame(bar, bg=BORDER, height=1).pack(fill="x")

        inner = tk.Frame(bar, bg=PANEL_BG)
        inner.pack(fill="both", expand=True, padx=12)

        # close button
        tk.Button(
            inner, text="✕  Close",
            font=("Segoe UI", 9, "bold"),
            bg=ACCENT, fg="white",
            activebackground=ACCENT_DIM, activeforeground="white",
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._on_close,
        ).pack(side="right", pady=8, padx=(8, 0))

        # pause button
        self._pause_btn = tk.Button(
            inner, text="⏸  Pause",
            font=("Segoe UI", 9, "bold"),
            bg=CARD_BG, fg=TEXT_PRIMARY,
            activebackground=ACCENT, activeforeground="white",
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._toggle_pause, state="disabled",
        )
        self._pause_btn.pack(side="left", pady=8, padx=(0, 16))

        # speed
        tk.Label(inner, text="Speed:", bg=PANEL_BG, fg=TEXT_DIM,
                 font=("Segoe UI", 9)).pack(side="left")
        self._speed_buttons = {}
        for spd, label in [(1, "1×"), (2, "2×"), (4, "4×"), (0, "MAX")]:
            btn = tk.Button(
                inner, text=label,
                font=("Segoe UI", 8, "bold"),
                bg=CARD_BG, fg=TEXT_PRIMARY,
                activebackground=ACCENT, activeforeground="white",
                relief="flat", padx=8, pady=3, cursor="hand2",
                command=lambda s=spd: self._set_speed(s),
            )
            btn.pack(side="left", padx=2, pady=8)
            self._speed_buttons[spd] = btn
        self._highlight_speed_btn(self._speed)

        tk.Label(
            inner,
            text="  ↑↓←→ / WASD · X=A · Y=B · Enter=Start · Bksp=Select",
            font=("Segoe UI", 8), bg=PANEL_BG, fg=TEXT_DIM,
        ).pack(side="left", padx=(16, 0))

        right_bar = tk.Frame(inner, bg=PANEL_BG)
        right_bar.pack(side="right")

        self._rom_lbl = tk.Label(
            right_bar, text="No ROM",
            font=("Segoe UI", 9), bg=PANEL_BG, fg=TEXT_DIM,
        )
        self._rom_lbl.pack(side="left", padx=(0, 14))

        self._fps_lbl = tk.Label(
            right_bar, text="FPS: --",
            font=("Courier", 9, "bold"),
            bg=PANEL_BG, fg=TEXT_FIRED, width=10, anchor="e",
        )
        self._fps_lbl.pack(side="right")

    # -----------------------------------------------------------------------
    # Theme
    # -----------------------------------------------------------------------

    def _apply_theme(self):
        ttk.Style(self).theme_use("clam")

    # -----------------------------------------------------------------------
    # Emulator lifecycle
    # -----------------------------------------------------------------------

    def _launch_emulator(self):
        if not self._rom_path or not self._rom_path.exists():
            messagebox.showerror("Error", f"ROM not found:\n{self._rom_path}")
            return

        if self._emulator:
            self._emulator.stop()
            self._emulator = None

        try:
            from gbc_patcher.emulator import Emulator
            emu = Emulator(rom_path=self._rom_path, headless=True, speed=self._speed)
            emu.start()
            self._emulator = emu
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to start emulator:\n{exc}")
            logger.exception("Emulator start failed")
            return

        self._rom_lbl.config(text=self._rom_path.name)
        self._pause_btn.config(state="normal")
        self._paused = False
        self._pause_btn.config(text="⏸  Pause")
        self._canvas.delete("placeholder")

        self._invinc_manager.register(self._emulator._pyboy)

        self._money_manager.register(self._emulator._pyboy)

        if not self._invinc_card_visible:
            self._invinc_card.pack(fill="x", padx=4, pady=(4, 2))
            self._invinc_card_visible = True

        if not self._team_cards_visible:
            for card in self._team_cards:
                card.pack(fill="x", padx=4, pady=(4, 2))
            self._team_cards_visible = True

        self.after(FRAME_MS, self._tick)

    # -----------------------------------------------------------------------
    # Frame loop
    # -----------------------------------------------------------------------

    def _tick(self):
        if self._emulator is None:
            return
        if not self._paused:
            alive = self._emulator.tick_once()
            if not alive:
                self._emulator = None
                return
            self._render_frame()
            self._money_manager.protect() 
            self._update_fps()
            if self._team_cards_visible:
                for card in self._team_cards:
                    card.refresh_current()
        self.after(FRAME_MS, self._tick)

    def _render_frame(self):
        try:
            from PIL import ImageTk, Image
            pil_img = self._emulator.screen_image
            if pil_img is None:
                return
            scaled = pil_img.resize((CANVAS_W, CANVAS_H), Image.NEAREST)
            self._tk_image = ImageTk.PhotoImage(scaled)
            self._canvas.create_image(0, 0, anchor="nw", image=self._tk_image)
        except Exception as exc:
            logger.debug("Frame render error: %s", exc)

    def _update_fps(self):
        self._fps_frames += 1
        now = time.perf_counter()
        elapsed = now - self._fps_last
        if elapsed >= 0.5:
            self._fps_display = self._fps_frames / elapsed
            self._fps_frames  = 0
            self._fps_last    = now
            self._fps_lbl.config(text=f"FPS: {self._fps_display:5.1f}")

    # -----------------------------------------------------------------------
    # Controls
    # -----------------------------------------------------------------------

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.config(text="▶  Resume", bg=ACCENT)
        else:
            self._pause_btn.config(text="⏸  Pause", bg=CARD_BG)
            self.after(FRAME_MS, self._tick)

    def _set_speed(self, speed: int):
        self._speed = speed
        self._highlight_speed_btn(speed)
        if self._emulator and self._emulator._pyboy:
            self._emulator._pyboy.set_emulation_speed(speed)

    def _highlight_speed_btn(self, speed: int):
        for s, btn in self._speed_buttons.items():
            btn.config(
                bg=ACCENT  if s == speed else CARD_BG,
                fg="white" if s == speed else TEXT_PRIMARY,
            )

    # -----------------------------------------------------------------------
    # File dialog
    # -----------------------------------------------------------------------

    def _open_rom(self):
        path = filedialog.askopenfilename(
            title="Open ROM",
            filetypes=[("Game Boy Color ROM", "*.gbc *.gb"), ("All files", "*.*")],
        )
        if path:
            self._rom_path = Path(path)
            self._launch_emulator()

    # -----------------------------------------------------------------------
    # Scroll helpers
    # -----------------------------------------------------------------------

    def _on_patch_list_resize(self, _event):
        self._patch_canvas.config(scrollregion=self._patch_canvas.bbox("all"))

    def _on_patch_canvas_resize(self, event):
        self._patch_canvas.itemconfig(self._patch_canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self._patch_canvas.yview_scroll(-1 * (event.delta // 120), "units")

    # -----------------------------------------------------------------------
    # Keyboard input
    # -----------------------------------------------------------------------

    def _bind_keys(self):
        self.bind("<KeyPress>",   self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self.focus_set()

    def _on_key_press(self, event):
        button = KEY_MAP.get(event.keysym)
        if button and self._emulator and self._emulator._pyboy:
            self._emulator._pyboy.button_press(button)

    def _on_key_release(self, event):
        button = KEY_MAP.get(event.keysym)
        if button and self._emulator and self._emulator._pyboy:
            self._emulator._pyboy.button_release(button)

    # -----------------------------------------------------------------------
    # Shutdown
    # -----------------------------------------------------------------------

    def _on_close(self):
        if self._emulator:
            self._emulator.stop()
        self.destroy()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch_gui(
    rom_path: Optional[str | Path] = None,
    speed: int = 1,
) -> None:
    """Launch the GUI. rom_path is optional; use File → Open ROM to load in-app."""
    app = GBCPatcherApp(rom_path=rom_path, initial_speed=speed)
    app.mainloop()
