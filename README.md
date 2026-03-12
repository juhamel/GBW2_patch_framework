# GBC Cheat Tool

A runtime cheat tool for Game Boy Color ROMs, built with Python and PyBoy.
Runs the game inside a tkinter window and applies cheats live via CPU hooks
and direct memory writes — no ROM modification required.

---

## Features

- **Game display** — 160×144 rendered at 3× scale inside the GUI
- **Invincibility** — per-team toggle; hooks the HP write-back instruction
  so units never lose HP in combat
- **Money editor** — per-team money control with preset buttons (±1K/5K/10K)
  and a free-input field that can add to or set the exact balance
- **Speed control** — 1×, 2×, 4×, or unlimited emulation speed
- **Pause / Resume**
- **Keyboard input** — play the game directly from the GUI

---

## Installation

```bash
# 1. Create and activate a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install the package
pip install -e .
```

**Dependencies** (installed automatically):
- `pyboy >= 2.0.0`
- `pillow >= 10.0.0`

---

## Usage

```bash
# Launch the GUI (open a ROM from File menu)
python -m gbc_patcher gui

# Launch with a ROM pre-loaded
python -m gbc_patcher gui path/to/game.gbc

# Launch at 2× speed
python -m gbc_patcher gui path/to/game.gbc --speed 2
```

---

## Controls

| Input | GBC button |
|---|---|
| Arrow keys / WASD | D-pad |
| X | A |
| Y | B |
| Enter | Start |
| Backspace | Select |

---

## Cheat reference

### 🛡 Invincibility

Hooks the instruction `LD [DE], A` at ROM address `bank=0, 0x3A81`.
This is the point where post-combat HP is written back to a unit's memory slot.

At hook time:
- `DE` holds the target unit's HP address
- `A` holds the new (reduced) HP value

When invincibility is enabled for a team, the hook replaces `A` with the
unit's **current** HP before the write executes, so the value never changes.

**Unit memory layout:**

| Team | Block | HP offset | Addresses |
|---|---|---|---|
| Red | `0xC980–0xCC0F` | `+8` per unit | `0xC988, 0xC998, … 0xCC08` (41 units) |
| White | `0xCC10–0xCE9F` | `+8` per unit | `0xCC18, 0xCC28, … 0xCE98` (41 units) |

---

### 💰 Money editor

Money is stored as a **17-bit little-endian integer** at two HIRAM addresses:

```
value = hi_byte × 65,536 + mi_byte × 256 + lo_byte     range: 0 – 99,999

```

| Team | Low byte | Mid byte | High byte |
|---|---|---|---|
| Red | `0xFFE6` | `0xFFE7` | `0xFFE8` |
| White | `0xFFE9` | `0xFFEA` | `0xFFEB`|

**Example:** `FFE9 = 0xF0`, `FFEA = 0x55`, `FFEB = 0x00` → `0x55 × 256 + 0xF0 = 22,000`

**Controls:**
- **Preset buttons** — instant ±1K / ±5K / ±10K
- **±Add mode** — type a number, click Apply → adds to current balance
- **=Set mode** — type a number, click Apply → sets exact balance
- Press **Enter** in the input field to trigger Apply

---

# Free Money Cheat

Instead of patching the game's money subtraction routine (which affects
both player and CPU), the tool uses a memory correction strategy.

Each frame:

1.  The current money value is read.
2.  If the value decreased while the cheat is active
3.  The previous value is restored.

Pseudo-logic:

current = read_money()

if cheat_enabled and current \< last_value: write_money(last_value)
else: last_value = current

Advantages:

-   affects only the selected team
-   does not modify game logic
-   stable across purchases and income events

------------------------------------------------------------------------


## Project structure

```
gbc_patcher/
├── __init__.py       — package exports
├── __main__.py       — enables python -m gbc_patcher
├── cli.py            — argument parser and entry point
├── emulator.py       — PyBoy wrapper
└── gui.py            — tkinter GUI, InvincibilityManager, TeamMoneyCard
pyproject.toml
README.md
```

---

## Notes

- The invincibility hook fires on every `LD [DE], A` at `0x3A81`. Because
  the unit HP addresses are stored in a `frozenset`, the lookup is O(1) and
  has no measurable performance impact at 60 fps.
- PyBoy hook callbacks receive `(context)` as a single argument. We pass
  `pyboy.register_file` as context to get direct CPU register access.
  Individual registers (`D`, `E`, `A`) are read/written on the
  `PyBoyRegisterFile` object; combined 16-bit registers like `DE` must be
  constructed manually: `de = (rf.D << 8) | rf.E`.
