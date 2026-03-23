with open(r"c:\Users\scopp\OneDrive\Documents\repos\ChordCoach-Companion\src\logic\services\chord_trainer.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "def _advance_dominant_motion" in line:
        print(f"{i+1}: {line.strip()}")
