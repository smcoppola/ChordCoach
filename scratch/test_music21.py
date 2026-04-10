from music21 import corpus
import traceback

def test_parse(name):
    try:
        s = corpus.parse(name)
        print(f"Success {name}: {type(s)}")
        return True
    except Exception as e:
        print(f"Fail {name}: {e}")
        return False

variants = [
    'erk5.abc',
    'essenFolksong/erk5.abc',
    'essenFolksong/erk5',
    'bach/bwv1.6.mxl',
    'bach/bwv1.6'
]

for v in variants:
    test_parse(v)
