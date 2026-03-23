# GBC Cheat Tool

A runtime cheat tool for Game Boy Color ROMs, built with Python and PyBoy.
Runs the game inside a tkinter window and applies cheats live via CPU hooks
and direct memory writes — no ROM modification required.

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
python -m gbc_patcher

# Launch with a ROM pre-loaded
python -m gbc_patcher gui path/to/game.gbc

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

## Project structure

```
gbc_patcher/
├── __init__.py       — package exports
├── __main__.py       — enables python -m gbc_patcher
├── cli.py            — argument parser and entry point
├── emulator.py       — PyBoy wrapper
└── gui.py            — tkinter GUI, InvincibilityManager, TeamMoneyCard
Abgabe/
├── Report_Binary_Hacking_GBW2.pdf - finished version of our report
├── Poster_Binary_Hacking_GBW2.pdf - finished version of our poster
├── RawReport/					   - Directory containing raw .tex and auxiliary files
├── RawPoster/					   - Directory containign raw .tex and auxiliary files
pyproject.toml
README.md
```

