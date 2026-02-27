import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

# Add src to the path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.database_manager import DatabaseManager # type: ignore

def main():
    db_path = project_root / "database" / "test_userdata.db"
    
    # Clean up previous tests
    if db_path.exists():
        db_path.unlink()
        
    print("Testing DatabaseManager...")
    db = DatabaseManager(db_path)
    
    # 1. Test Song Insert
    print("Inserting song play for 'Fur Elise'...")
    db.record_song_play("/path/to/fur_elise.mid", "Fur Elise", 10.5)
    
    # 2. Test Chord Attempts (Today)
    print("Inserting recent chord attempts (C Major, G Major)...")
    db.record_chord_attempt("C Major", success=True, latency_ms=120)
    db.record_chord_attempt("C Major", success=True, latency_ms=100)
    db.record_chord_attempt("G Major", success=False, latency_ms=300)
    
    # 3. Time Travel (Modify the DB to pretend F Minor was played 3 days ago)
    print("Simulating old chord attempt (F Minor) from 3 days ago...")
    three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO chords (name, last_played, success_count, fail_count, avg_latency_ms)
            VALUES (?, ?, ?, ?, ?)
        ''', ("F Minor", three_days_ago, 10, 2, 250))
        conn.commit()
        
    # 4. Emulate Application Boot (Run Decay Algorithm)
    print("\nRunning Skill Decay Algorithm...")
    decayed = db.calculate_skill_decay(decay_hours=48, decay_rate=0.50)
    
    if len(decayed) > 0:
        print(f"Algorithm correctly identified {len(decayed)} decayed chords:")
        for chord in decayed:
             print(f"- {chord['name']}: Success count decayed from {chord['old_success_count']} -> {chord['new_success_count']}")
    else:
        print("ERROR: Algorithm failed to identify the 3-day old chord.")
        sys.exit(1)
        
    # 5. Get Coach Context
    print("\nGenerated AI Coach Context:")
    context = db.get_coach_context()
    print("---")
    print(context)
    print("---")
    
    print("\nTest passed successfully.")

if __name__ == "__main__":
    main()
