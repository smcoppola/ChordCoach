import sys
from pathlib import Path
import time
from PySide6.QtCore import QCoreApplication

# Add src to the path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.repertoire_crawler import RepertoireCrawler

class TestCrawlerHarness:
    def __init__(self):
        self.crawler = RepertoireCrawler()
        self.crawler.downloadComplete.connect(self.on_success)
        self.crawler.downloadFailed.connect(self.on_fail)
        self.finished = False
        self.success = False

    def on_success(self, filepath):
        print(f"\n--- SUCCESS ---\nFile downloaded to: {filepath}")
        
        # Verify it actually exists and has size
        f = Path(filepath)
        if f.exists() and f.stat().st_size > 100:
            print("Verified file exists and appears to be a valid payload.")
            self.success = True
        else:
            print("ERROR: File is missing or empty!")
            
        self.finished = True

    def on_fail(self, error):
        print(f"\n--- FAILURE ---\n{error}")
        self.finished = True

def main():
    # We need a QCoreApp to process the pySignals
    app = QCoreApplication(sys.argv)
    
    print("Testing BitMidi Repertoire Crawler...")
    tester = TestCrawlerHarness()
    
    # Let's search for a classic
    query = "Fur Elise"
    print(f"Triggering search for: {query}")
    tester.crawler.search_and_download(query)
    
    # Run the event loop until the threaded worker finishes and emits the signal
    timeout = 15 # Give it 15 seconds max to do the 2 network hops
    start_time = time.time()
    
    while not tester.finished and (time.time() - start_time) < timeout:
        app.processEvents()
        time.sleep(0.1)
        
    if not tester.finished:
        print("\nTest failed: Timeout reached waiting for callback signals.")
        sys.exit(1)
        
    if not tester.success:
         sys.exit(1)

if __name__ == "__main__":
    main()
