import music21
from music21 import corpus, stream
import os

try:
    path = "airdsAirs/book1.abc"
    s = corpus.parse(path)
    print(f"Path: {path}")
    print(f"Type: {type(s)}")
    if isinstance(s, stream.Opus):
        print(f"Is Opus: Yes, Count: {len(s)}")
        for i, tune in enumerate(s):
            if tune.metadata:
                print(f"  Tune {i}: {tune.metadata.title}")
            else:
                print(f"  Tune {i}: No metadata")
    else:
        print("Is Opus: No")
except Exception as e:
    print(f"Error: {e}")
