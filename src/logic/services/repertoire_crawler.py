import requests # type: ignore
from bs4 import BeautifulSoup # type: ignore
from PySide6.QtCore import QObject, Signal, Slot # type: ignore
from pathlib import Path
import urllib.parse
import threading

class RepertoireCrawler(QObject):
    downloadComplete = Signal(str) # Emits the filepath of the downloaded midi
    downloadFailed = Signal(str) # Emits an error message
    
    def __init__(self):
        super().__init__()
        # Use a local cache directory in the project for now
        self.cache_dir = Path(__file__).parent.parent.parent.parent / "database" / "repertoire"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = "https://bitmidi.com"
        
    @Slot(str)
    def search_and_download(self, query: str):
        """Asynchronously triggers search and download to avoid blocking UI."""
        thread = threading.Thread(target=self._search_worker, args=(query,), daemon=True)
        thread.start()
        
    def _search_worker(self, query: str):
        try:
            print(f"Repertoire Crawler: Searching for '{query}'...")
            encoded_query = urllib.parse.quote(query)
            search_url = f"{self.base_url}/search?q={encoded_query}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            response = requests.get(search_url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            links = soup.find_all('a', href=True)
            target_page_url = ""
            
            for link in links:
                href = link['href']
                if "-mid" in href and not href.startswith("/search") and not href.startswith("/random"):
                    # We found a direct link to a song page
                    target_page_url = self.base_url + href
                    break
                    
            if not target_page_url:
                err = f"No MIDI files found on BitMidi for query: '{query}'"
                print(f"Repertoire Crawler: {err}")
                self.downloadFailed.emit(err)
                return
                
            print(f"Repertoire Crawler: Found song page {target_page_url}, extracting download link...")
            self._download_from_page(target_page_url, query)
            
        except Exception as e:
            err = f"Search failed: {e}"
            print(f"Repertoire Crawler: {err}")
            self.downloadFailed.emit(err)
            
    def _download_from_page(self, page_url: str, original_query: str):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(page_url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # BitMidi download links specifically say "Download MIDI"
            download_link = soup.find('a', string=lambda t: t and 'Download' in t and 'MIDI' in t)
            
            if not download_link or not download_link.get('href'):
                 # Fallback: find any a-tag that directly links to a file downloaded from their CDN
                 links = soup.find_all('a', href=True)
                 for l in links:
                     if "download" in l.get('href', '').lower() or l.get('href', '').endswith('.mid'):
                         download_link = l
                         break

            if not download_link or not download_link.get('href'):
                 err = "Could not locate the actual download link on the song page."
                 print(f"Repertoire Crawler: {err}")
                 self.downloadFailed.emit(err)
                 return
                 
            dl_href = download_link['href']
            # Sometimes it's a relative link
            if dl_href.startswith('/'):
                 actual_dl_url = self.base_url + dl_href
            else:
                 actual_dl_url = dl_href

            print(f"Repertoire Crawler: Downloading from {actual_dl_url}...")
            
            midi_res = requests.get(actual_dl_url, headers=headers)
            midi_res.raise_for_status()
            
            # Sanitize filename
            safe_query = "".join([c if c.isalnum() else "_" for c in original_query])
            filename = f"{safe_query}.mid"
            filepath = self.cache_dir / filename
            
            with open(filepath, 'wb') as f:
                f.write(midi_res.content)
                
            print(f"Repertoire Crawler: Successfully downloaded to {filepath}")
            self.downloadComplete.emit(str(filepath))
            
        except Exception as e:
            err = f"Download failed: {e}"
            print(f"Repertoire Crawler: {err}")
            self.downloadFailed.emit(err)
