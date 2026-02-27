import mido  # type: ignore
import pretty_midi  # type: ignore
from PySide6.QtCore import QObject, Signal, Slot  # type: ignore
from dataclasses import dataclass, asdict
from typing import List, Dict

@dataclass
class VisualBlock:
    pitch: int
    start_time: float
    duration: float
    color: str

class MidiIngestor(QObject):
    # Emit a list of dictionaries representing the 'VisualBlocks'
    midiParsed = Signal(list)
    
    # Optional signal for metadata
    midiMetadata = Signal(dict)

    def __init__(self):
        super().__init__()

    @Slot(str)
    def ingest_file(self, file_path: str):
        try:
            print(f"Ingesting MIDI file: {file_path}")
            pm = pretty_midi.PrettyMIDI(file_path)
            
            # Find the best track for the piano notation
            target_track = self._select_piano_track(pm)
            
            if not target_track:
                print("Warning: No suitable tracks found in MIDI file.")
                self.midiParsed.emit([])
                return

            blocks = self._translate_to_blocks(target_track.notes)
            
            # Emit metadata
            metadata = {
                "duration": pm.get_end_time(),
                "instruments": [i.name for i in pm.instruments],
                "note_count": len(target_track.notes),
                "selected_track": target_track.name
            }
            self.midiMetadata.emit(metadata)
            
            # Emit the list of raw dictionaries for QML to easily consume
            # We construct dict directly instead of using asdict() due to static analysis struggles with it
            raw_blocks = [{"pitch": b.pitch, "start_time": b.start_time, "duration": b.duration, "color": b.color} for b in blocks]
            self.midiParsed.emit(raw_blocks)
            print(f"Successfully processed {len(blocks)} visual blocks.")
            
        except Exception as e:
            print(f"Error ingesting MIDI file: {e}")
            self.midiParsed.emit([])

    def _select_piano_track(self, pm: pretty_midi.PrettyMIDI) -> pretty_midi.Instrument | None:
        """Heuristically select the best track for a piano tutorial."""
        if not pm.instruments:
            return None
            
        # 1. Look for explicit Acoustic Grand Piano (program 0)
        for inst in pm.instruments:
            if not inst.is_drum and inst.program == 0:
                print(f"Selected acoustic grand piano track: {inst.name}")
                return inst
                
        # 2. Fallback: Find the non-drum track with the most notes (likely the melody/chord track)
        best_track = None
        max_notes = 0
        for inst in pm.instruments:
            if not inst.is_drum and len(inst.notes) > max_notes:
                max_notes = len(inst.notes)
                best_track = inst
                
        if best_track is not None:
            print(f"Fallback track selected (most notes): {best_track.name}")  # type: ignore
            
        return best_track

    def _translate_to_blocks(self, notes: List[pretty_midi.Note]) -> List[VisualBlock]:
        """Convert pretty_midi Notes to our proprietary physical duration blocks."""
        blocks = []
        for note in notes:
            # Enforce a minimum duration for playability on the hybrid UI
            duration = max(note.end - note.start, 0.05) 
            blocks.append(
                VisualBlock(
                    pitch=note.pitch,
                    start_time=note.start,
                    duration=duration,
                    color=self.get_color_for_note(note.pitch)
                )
            )
            
        # Ensure they are sorted by time so the QML scroller can process them sequentially
        blocks.sort(key=lambda b: b.start_time)
        return blocks

    def get_color_for_note(self, pitch: int) -> str:
        """
        Assigns standard colors based on the pitch octave class.
        In a full version, this would be highly adaptive based on hand span.
        """
        # Map 12 chromatic pitches to a distinct palette to help with hand-span awareness
        colors = [
            "#FF2B2B", # C - Red
            "#FF7A2B", # C# - Orange
            "#FFD02B", # D - Yellow
            "#C3FF2B", # D# - Lime
            "#55FF2B", # E - Green
            "#2BFF93", # F - Mint
            "#2BFFE4", # F# - Cyan
            "#2B93FF", # G - Blue
            "#502BFF", # G# - Indigo
            "#AC2BFF", # A - Purple
            "#FF2BE1", # A# - Magenta
            "#FF2B6D", # B - Pink
        ]
        return colors[pitch % 12]
