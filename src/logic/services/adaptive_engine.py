import os
import json
import urllib.request
import threading
from PySide6.QtCore import QObject, Signal, Slot, Property # type: ignore

class AdaptiveEngineService(QObject):
    """
    Manages Phase 2: Targeted Micro-Lesson.
    Analyzes the user's performance and queries Gemini to find a specific
    YouTube video to address their most critical bottleneck.
    """
    bottleneckChanged = Signal()
    loadingChanged = Signal()

    def __init__(self, db_manager, settings_manager=None):
        super().__init__()
        self.db = db_manager
        self.settings = settings_manager
        self._video_url = ""
        self._description = ""
        self._is_loading = False

    @Property(str, notify=bottleneckChanged)
    def recommendedVideoUrl(self) -> str:
        return self._video_url

    @Property(str, notify=bottleneckChanged)
    def bottleneckDescription(self) -> str:
        return self._description

    @Property(bool, notify=loadingChanged)
    def isLoading(self) -> bool:
        return self._is_loading

    @Slot()
    def analyze_performance(self):
        """Called when the Phase 2 view is opened."""
        if self._is_loading:
            return
            
        self._is_loading = True
        self._description = "Analyzing performance and finding the best lesson..."
        self._video_url = ""
        self.bottleneckChanged.emit()
        self.loadingChanged.emit()
        
        # Fetch the real raw skill matrix from the database
        user_context = self.db.get_coach_context()
        
        # Query Gemini in a background thread to prevent UI freezing
        threading.Thread(target=self._query_gemini_for_lesson, args=(user_context,), daemon=True).start()

    def _query_gemini_for_lesson(self, user_context: str):
        api_key = self.settings.apiKey if self.settings else os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            self._set_error("No API key found. Cannot connect to AI Coach.")
            return

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        
        prompt = f"""You are 'ChordCoach', an encouraging piano instructor. 
        
Here is the user's current skill matrix based on recent practice sessions:
{user_context}

Analyze this context to determine the single most pressing bottleneck or weakness the user has right now. 
If the context is empty or shows no struggles, assume they are a beginner who needs to learn basic pop chord transitions.

Return ONLY a raw JSON object (no markdown formatting, no backticks) with two keys:
"bottleneck_description": "A brief 2-sentence encouraging explanation of why the specific chords they are struggling with are hard, and the mechanical fix we will focus on in a video."
"youtube_search_query": "A targeted search query to find this exact technique (e.g. 'piano tutorial transition C major to G major')."
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2} # Low temp for structured output
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
                
                # Default fallback values
                desc = "It looks like you're struggling with the C to G pivot. Let's watch this quick tip!"
                search_query = "piano tutorial transition C major G major"
                
                from urllib.parse import quote
                import re
                
                # Extract anything that looks like JSON
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                clean_text = json_match.group(0) if json_match else text
                
                try:
                    data = json.loads(clean_text)
                    desc = data.get("bottleneck_description", desc)
                    search_query = data.get("youtube_search_query", search_query)
                except json.JSONDecodeError:
                    print(f"AdaptiveEngine: Could not parse JSON from Gemini. Falling back to default search.")
                
                # Format to a standard YouTube search results page
                # We use the mobile/tv layout to make it look cleaner in the player window if possible,
                # but standard results works great in WebEngine.
                vid_url = f"https://www.youtube.com/results?search_query={quote(search_query)}"
                
                self._update_results(desc, vid_url)

        except Exception as e:
            print(f"AdaptiveEngine: REST API error: {e}")
            self._set_error("Failed to load micro-lesson due to network error.")

    def _update_results(self, desc: str, vid: str):
        self._description = desc
        self._video_url = vid
        self._is_loading = False
        # Signals emitted from background threads queue safely to the main thread
        self.bottleneckChanged.emit()
        self.loadingChanged.emit()

    def _set_error(self, msg: str):
        self._update_results(msg, "")
