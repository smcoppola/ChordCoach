import os
import pytest
from logic.services.music21_service import Music21Service

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))


def test_simplify_groups_meter_preservation(tmp_user_songs_dir):
    service = Music21Service()
    groups = [
        {"offset": 0.0, "duration": 1.0, "notes": [(60, "right"), (64, "right"), (67, "right"), (72, "right")]},
        {"offset": 1.0, "duration": 1.0, "notes": [(48, "left")]},
        {"offset": 2.0, "duration": 1.0, "notes": [(60, "right"), (64, "right")]},
    ]

    # Level 1 cap for RH notes is 2, LH is 1
    simplified = service._simplify_groups(groups, level=1)
    assert len(simplified[0]["notes"]) == 2

    # Score rebuild carries 3/4 meter
    time_sigs = [{"offset": 0.0, "numerator": 3, "denominator": 4}]
    score, key_name, key_sharps = service._build_score_from_groups(
        simplified, time_signatures=time_sigs
    )
    steps, barlines, extra_meta = service._extract_steps_from_score(score)

    assert extra_meta["time_signatures"] == time_sigs
