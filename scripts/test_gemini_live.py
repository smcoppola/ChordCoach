import sys
import os
import time
from pathlib import Path

# Add src to the path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.gemini_service import GeminiService

class TestHarness:
    def __init__(self, api_key):
        self.service = GeminiService(api_key=api_key)
        self.service.connectionStatusChanged.connect(self.on_conn_changed)
        self.service.responseReceived.connect(self.on_response)
        self.is_connected = False
        self.has_responded = False

    def on_conn_changed(self, connected):
        self.is_connected = connected
        print(f"Connection state changed: {connected}")
        
        if connected:
            print("Sending mock audio chunk...")
            # Give it a tiny bit of time to send the setup msg
            time.sleep(1.0)
            
            # Send 1 second of silence (16kHz mock PCM data)
            mock_pcm = [0.0] * 16000
            self.service.send_audio_chunk(mock_pcm)

    def on_response(self, text):
        print(f"\n--- AI RESPONSE ---\n{text}\n-------------------")
        self.has_responded = True

def main():
    # Load API key directly from .env for the test script
    # (In the real app, this should be handled globally or via user input)
    env_file = project_root / ".env"
    if env_file.exists():
        # Handle potential utf-16 encoding from powershell echo
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(env_file, "r", encoding="utf-16") as f:
                lines = f.readlines()
                
        for line in lines:
            if line.strip().startswith("GOOGLE_API_KEY="):
                os.environ["GOOGLE_API_KEY"] = line.strip().split("=", 1)[1]

    api_key = os.environ.get("GOOGLE_API_KEY")

    if not api_key or api_key == "YOUR_API_KEY_HERE":
        print("Error: GOOGLE_API_KEY environment variable not set or is still a placeholder in .env")
        sys.exit(1)
        
    print("Testing Gemini Live API WebSocket integration with genuine key...")
    tester = TestHarness(api_key=api_key)
    
    tester.service.connect_service()
    
    # Wait for connection and response (max 5 seconds since it should fail auth fast)
    timeout = 5
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if tester.has_responded:
            break
        time.sleep(0.5)
        
    tester.service.disconnect_service()
    time.sleep(0.5)
    
if __name__ == "__main__":
    main()
