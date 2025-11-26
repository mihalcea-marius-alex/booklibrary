import sys
import threading
import webbrowser
import socket
import time
import os
import io
from django.core.management import execute_from_command_line
from pystray import Icon, Menu, MenuItem
from PIL import Image

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bookmanager.settings")


def get_icon_path():
    """Get the path to the icon file, works both in dev and when frozen."""
    base_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_path, 'favicon.png')
    if os.path.exists(icon_path):
        return icon_path
    else:
        print(icon_path)

def create_tray_icon():
    try:
        image = Image.open(get_icon_path())
    except Exception:
        image = Image.new('RGB', (64, 64), color='blue')

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    menu = Menu(MenuItem('Quit', on_quit))
    icon = Icon("BookManager", image, "Book Manager Server", menu)
    icon.run()

def wait_for_server(host="127.0.0.1", port=8000, timeout=20):
    """Wait until the Django dev server is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    return False

def open_browser_when_ready():
    url = "http://127.0.0.1:8000/"
    if wait_for_server("127.0.0.1", 8000):
        webbrowser.open_new(url)

def run_server():
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    threading.Thread(target=create_tray_icon, daemon=False).start()

    execute_from_command_line(["manage.py", "runserver", "--noreload"])

if __name__ == "__main__":
    run_server()
