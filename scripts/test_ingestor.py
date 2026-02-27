import sys
from pathlib import Path

# Add src to the path so we can import our logic
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.midi_ingestor import MidiIngestor

def on_parsed(blocks):
    if not blocks:
        print("Empty blocks returned!")
        sys.exit(1)
        
    print(f"\n--- Output of {len(blocks)} Visual Blocks ---")
    
    # Print the first 10
    for i, b in enumerate(blocks[:10]):
        print(f"Block {i+1}: Note {b['pitch']} | Time: {b['start_time']:.2f}s | Dur: {b['duration']:.2f}s | Color: {b['color']}")
        
    if len(blocks) > 10:
        print("...[truncated]")

def on_metadata(meta):
    print("\n--- MIDI Metadata ---")
    for k, v in meta.items():
        print(f"{k}: {v}")

def main():
    test_file = project_root / "database" / "test_song.mid"
    if not test_file.exists():
        print(f"Error: Could not find {test_file}")
        sys.exit(1)
        
    ingestor = MidiIngestor()
    
    # Connect signals
    ingestor.midiParsed.connect(on_parsed)
    ingestor.midiMetadata.connect(on_metadata)
    
    print("Testing MidiIngestor...")
    ingestor.ingest_file(str(test_file))

if __name__ == "__main__":
    main()
