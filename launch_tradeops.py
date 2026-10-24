"""Start the local dashboard and open the browser after it becomes ready."""
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8501'


def ready():
    try:
        with urlopen(URL + '/_stcore/health', timeout=1) as response:
            return response.status == 200 and response.read().strip() == b'ok'
    except (URLError, OSError):
        return False


def main():
    if ready():
        print('Opening the running Streamlit server.')
        webbrowser.open(URL)
        return 0
    print('Starting TradeOps. Keep this window open while using the app.')
    process = subprocess.Popen(
        [sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
         '--server.address', '127.0.0.1', '--server.port', '8501', '--server.headless', 'true'],
        cwd=ROOT,
    )
    try:
        for _ in range(60):
            if process.poll() is not None:
                print('TradeOps could not start. Review the message above.')
                return process.returncode or 1
            if ready():
                webbrowser.open(URL)
                break
            time.sleep(0.5)
        else:
            print(f'Browser startup timed out. You can try opening {URL} manually.')
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
