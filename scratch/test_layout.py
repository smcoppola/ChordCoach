from PySide6.QtGui import QGuiApplication, QFontDatabase
import os
from pathlib import Path
import sys

# Mock app
app = QGuiApplication(['test'])

# Define paths
project_root = Path('c:/Users/scopp/OneDrive/Documents/repos/ChordCoach-Companion')
sys.path.append(os.fspath(project_root / 'src'))

# Register fonts
font_dir = project_root / 'src/resources/fonts'
if font_dir.exists():
    for font_file in font_dir.glob('Bravura.otf'):
        QFontDatabase.addApplicationFont(os.fspath(font_file))

from ui.notation_view import NotationView

view = NotationView()
# Mock spacing
s = 10.0
# Mock notes: C4 (60) and D4 (62) - a second apart
notes = [
    {'pitch': 60, 'start_beat': 0.0},
    {'pitch': 62, 'start_beat': 0.0}
]

layout = view._get_layout_for_notes(notes, 0.0, 100.0, 100.0, 150.0, 350.0, s)

for i, l in enumerate(layout):
    p = l['note']['pitch']
    xo = l['notehead_offset_x']
    ao = l['accidental_offset_x']
    print(f'Note {i} (Pitch {p}): x_offset={xo}, acc_offset={ao}')

# Check for stagger
if any(l['notehead_offset_x'] > 0 for l in layout):
    print('SUCCESS: Interval of a second detected and staggered.')
else:
    print('FAILURE: Staggering not detected for interval of a second.')

# Check for accidental collision: C4# (61) and D4# (63)
notes_acc = [
    {'pitch': 61, 'start_beat': 1.0},
    {'pitch': 63, 'start_beat': 1.0}
]
layout_acc = view._get_layout_for_notes(notes_acc, 0.0, 100.0, 100.0, 150.0, 350.0, s)
for i, l in enumerate(layout_acc):
    p = l['note']['pitch']
    ao = l['accidental_offset_x']
    print(f'Accidental Note {i} (Pitch {p}): acc_offset={ao}')

if any(l['accidental_offset_x'] < 0 for l in layout_acc):
    print('SUCCESS: Accidental collision detected and resolved.')
else:
    print('FAILURE: Accidental collision not resolved.')
