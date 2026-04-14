import os
import json
import urllib.request
import zipfile
import shutil
from core.bootstrap import get_user_data_dir

class CorpusManager:
    """
    Handles checking for, downloading, and configuring the music21 corpus at runtime.
    """
    
    @staticmethod
    def get_corpus_base_path():
        """Returns the platform-specific writable path for music21 assets."""
        base_path = get_user_data_dir()
        return os.path.join(base_path, "music21_assets")

    @staticmethod
    def is_corpus_present():
        """Checks if the music21 corpus exists in the local storage."""
        path = CorpusManager.get_corpus_base_path()
        # The extraction puts everything under 'music21' subfolder
        corpus_dir = os.path.join(path, 'music21', 'corpus')
        return os.path.isdir(corpus_dir)

    @staticmethod
    def download_and_extract(progress_callback=None):
        """
        Downloads the music21 wheel from PyPI and extracts the corpus.
        progress_callback: function taking a float (0.0 to 1.0)
        """
        target_path = CorpusManager.get_corpus_base_path()
        os.makedirs(target_path, exist_ok=True)
        
        # Use a temporary directory for download/extraction
        tmp_dir = os.path.join(os.path.expanduser('~'), '.chordcoach_corpus_tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        whl_path = os.path.join(tmp_dir, 'music21.whl')

        def reporthook(block_count, block_size, total_size):
            if progress_callback and total_size > 0:
                percent = min(1.0, (block_count * block_size) / total_size)
                progress_callback(percent)

        try:
            # 1. Fetch metadata from PyPI
            pypi_url = 'https://pypi.org/pypi/music21/json'
            with urllib.request.urlopen(pypi_url) as r:
                info = json.loads(r.read())
            
            # Find the universal wheel
            wheel_info = next(
                u for u in info['urls']
                if u['filename'].endswith('none-any.whl')
            )
            download_url = wheel_info['url']

            # 2. Download
            if progress_callback:
                progress_callback(0.0)
            urllib.request.urlretrieve(download_url, whl_path, reporthook=reporthook)

            # 3. Extract just the 'music21' package folder from the wheel
            with zipfile.ZipFile(whl_path, 'r') as zf:
                all_files = zf.namelist()
                # Filtering for everything in the core package (includes corpus, etc.)
                # But we'll exclude what we don't need to save space during extraction too
                excluded_prefixes = ('music21/documentation/', 'music21/demos/', 'music21/test/')
                
                members = [
                    m for m in all_files
                    if m.startswith('music21/') and not any(m.startswith(p) for p in excluded_prefixes)
                ]
                zf.extractall(tmp_dir, members=members)

            # 4. Move to final destination
            src_pkg = os.path.join(tmp_dir, 'music21')
            dest_pkg = os.path.join(target_path, 'music21')
            
            if os.path.exists(dest_pkg):
                shutil.rmtree(dest_pkg)
            
            shutil.move(src_pkg, dest_pkg)
            
            # Final 100% signal
            if progress_callback:
                progress_callback(1.0)
                
            return True

        except Exception as e:
            print(f"CorpusManager Error: {e}")
            raise e
        finally:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def configure_environment():
        """Points music21 to the locally downloaded corpus."""
        try:
            from music21 import environment
            path = CorpusManager.get_corpus_base_path()
            corpus_dir = os.path.join(path, 'music21', 'corpus')
            
            us = environment.UserSettings()
            us['localCorpusPath'] = corpus_dir
            print(f"CorpusManager: Successfully pointed localCorpusPath to {corpus_dir}")
        except Exception as e:
            print(f"CorpusManager Environment Error: {e}")
