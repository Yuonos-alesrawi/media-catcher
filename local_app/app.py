"""Media Catcher: local server + tray icon + automatic yt-dlp updates.

    pythonw app.py            normal run (no window, icon in the system tray)
    python  app.py --no-tray  server only, in the console (for testing and development)
"""
import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

IS_WIN = os.name == "nt"
HOST, PORT = "127.0.0.1", 8765
MUTEX_NAME = "MediaCatcherMutex"  # must match AppMutex in setup.iss
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".media-catcher") / "MediaCatcher"
LOG_FILE = DATA_DIR / "app.log"
STATE_FILE = DATA_DIR / "state.json"

UPDATE_EVERY = 24 * 3600  # update yt-dlp once a day
RETRY_AFTER = 6 * 3600    # if the update fails (no internet) retry after 6 hours
IDLE_POLL = 5             # seconds between checks that downloads have finished, before updating
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------- Logging
def setup_logging() -> None:
    """pythonw runs without a console (stdout and stderr are None), which breaks uvicorn and print, so we redirect them to a file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2_000_000:
                LOG_FILE.unlink()
        except OSError:
            pass
        sys.stdout = sys.stderr = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
    print(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} start ---")


# ---------------------------------------------------------------- Saved state
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(**kw) -> None:
    st = load_state()
    st.update(kw)
    try:
        STATE_FILE.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass


def update_due(state: dict, now: float = None) -> bool:
    now = now if now is not None else time.time()
    return now - state.get("last_ok", 0) > UPDATE_EVERY and now - state.get("last_try", 0) > RETRY_AFTER


# ---------------------------------------------------------------- Single instance
_mutex = None


def acquire_single_instance() -> bool:
    global _mutex
    if not IS_WIN:
        return True
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k.CreateMutexW(None, False, MUTEX_NAME)
    return k.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def release_single_instance() -> None:
    global _mutex
    if IS_WIN and _mutex:
        k = ctypes.windll.kernel32
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.CloseHandle(_mutex)
        _mutex = None


def port_busy() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def wait_port_free(timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not port_busy():
            return True
        time.sleep(0.3)
    return not port_busy()


# ---------------------------------------------------------------- System helpers
def message_box(text: str, title: str = "Media Catcher") -> None:
    if IS_WIN:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)  # error icon
    else:
        print(f"{title}: {text}")


def confirm(text: str, title: str = "Media Catcher") -> bool:
    if IS_WIN:
        return ctypes.windll.user32.MessageBoxW(None, text, title, 0x24) == 6  # Yes/No buttons, 6 = Yes
    return True


def open_path(p) -> None:
    p = str(p)
    try:
        if IS_WIN:
            os.startfile(p)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:  # noqa: BLE001
        print("open_path failed:", e)


def launch_command() -> str:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else exe}" "{APP_DIR / "app.py"}"'


def autostart_enabled() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "MediaCatcher")
        return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "MediaCatcher", 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, "MediaCatcher")
            except FileNotFoundError:
                pass


def make_icon_image():
    """Tray icon: a blue square with a white download arrow (drawn in code, no image files)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(37, 99, 235, 255))
    d.polygon([(32, 46), (17, 30), (27, 30), (27, 13), (37, 13), (37, 30), (47, 30)], fill="white")
    d.rectangle((16, 50, 48, 54), fill="white")
    return img


# ---------------------------------------------------------------- yt-dlp updates
def pip_python() -> str:
    exe = Path(sys.executable)
    py = exe.with_name("python.exe")  # we need python.exe (not pythonw) so pip's output can be captured
    return str(py if py.exists() else exe)


def update_ytdlp() -> tuple:
    """Updates yt-dlp (and its components) with pip. Returns (succeeded, version_changed)."""
    cmd = [pip_python(), "-m", "pip", "install", "-U", "--disable-pip-version-check",
           "--no-warn-script-location", "--no-cache-dir", "--timeout", "10", "--retries", "1",
           "yt-dlp[default]"]
    flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=flags)
    except Exception as e:  # noqa: BLE001
        print("update failed:", e)
        return False, False
    out = (r.stdout or "") + (r.stderr or "")
    print("pip output (tail):", out[-400:])
    ok = r.returncode == 0
    return ok, ok and "Successfully installed" in out


# ---------------------------------------------------------------- Server
class ServerThread:
    def __init__(self):
        import uvicorn
        import server  # imported here so PATH and yt-dlp are ready after any update
        self.mod = server
        cfg = uvicorn.Config(server.app, host=HOST, port=PORT, log_level="warning")
        self.uv = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.uv.run, name="uvicorn", daemon=True)

    def start(self, timeout: float = 20.0) -> None:
        self.thread.start()
        end = time.time() + timeout
        while time.time() < end:
            if self.uv.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError("The local server failed to start (see app.log)")
            time.sleep(0.1)
        raise RuntimeError("Timed out waiting for the local server to start")

    def alive(self) -> bool:
        return self.thread.is_alive()

    def stop(self, timeout: float = 8.0) -> None:
        self.uv.should_exit = True
        self.thread.join(timeout)


def restart_app(srv: "ServerThread") -> None:
    print("restarting...")
    srv.stop()
    release_single_instance()
    flags = (0x00000008 | 0x00000200) if IS_WIN else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, str(APP_DIR / "app.py"), *sys.argv[1:]],
                     close_fds=True, creationflags=flags, cwd=str(APP_DIR))
    os._exit(0)


# ---------------------------------------------------------------- Tray icon and menu
class Controller:
    def __init__(self, srv: ServerThread, auto_update: bool):
        self.srv = srv
        self.auto_update = auto_update
        self.icon = None
        self._update_lock = threading.Lock()

    # -- info
    @property
    def version(self) -> str:
        return self.srv.mod.APP_VERSION

    def status_text(self) -> str:
        n = self.srv.mod.active_jobs()
        return f"Active downloads: {n}" if n else "Ready"

    def notify(self, msg: str) -> None:
        if not msg or self.icon is None:
            return
        try:
            self.icon.notify(msg, "Media Catcher")
        except Exception as e:  # noqa: BLE001
            print("notify failed:", e)

    # -- menu commands (pystray expects the (icon, item) signature)
    def open_downloads(self, icon=None, item=None):
        open_path(self.srv.mod.DOWNLOAD_DIR)

    def open_extension(self, icon=None, item=None):
        open_path(APP_DIR / "extension")

    def open_log(self, icon=None, item=None):
        if LOG_FILE.exists():
            open_path(LOG_FILE)

    def toggle_autostart(self, icon=None, item=None):
        try:
            set_autostart(not autostart_enabled())
        except Exception as e:  # noqa: BLE001
            print("autostart failed:", e)

    def manual_update(self, icon=None, item=None):
        threading.Thread(target=self.run_update, args=(True,), daemon=True).start()

    def quit(self, icon=None, item=None):
        if self.srv.mod.active_jobs() and not confirm("Downloads are in progress. Quit and cancel them?"):
            return
        if self.icon is not None:
            self.icon.stop()

    # -- updates
    def run_update(self, manual: bool) -> None:
        if not self._update_lock.acquire(blocking=False):
            return
        mod = self.srv.mod
        try:
            if mod.active_jobs():
                self.notify("The yt-dlp update will start when the current downloads finish.")
                while mod.active_jobs():
                    time.sleep(IDLE_POLL)
            elif manual:
                self.notify("Checking for a yt-dlp update...")
            mod.accepting.clear()  # no new jobs while files are being replaced
            ok, changed = update_ytdlp()
            now = time.time()
            save_state(last_try=now, **({"last_ok": now} if ok else {}))
            if ok and changed:
                self.notify("yt-dlp was updated. Restarting the app...")
                time.sleep(2)
                restart_app(self.srv)  # never returns
            mod.accepting.set()
            if manual:
                self.notify("yt-dlp is already up to date." if ok else "The update failed. Check your internet connection.")
        finally:
            self._update_lock.release()

    def auto_update_loop(self) -> None:
        time.sleep(60)
        while True:
            if update_due(load_state()):
                self.run_update(False)
            time.sleep(3600)

    # -- running
    def run_tray(self) -> None:
        import pystray
        Item = pystray.MenuItem
        menu = pystray.Menu(
            Item(lambda i: f"Media Catcher v{self.version}", None, enabled=False),
            Item(lambda i: self.status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            Item("Open downloads folder", self.open_downloads, default=True),
            Item("Update yt-dlp now", self.manual_update),
            Item("Start with Windows", self.toggle_autostart, checked=lambda i: autostart_enabled(), visible=IS_WIN),
            Item("Extension folder", self.open_extension),
            Item("View log", self.open_log),
            pystray.Menu.SEPARATOR,
            Item("Quit", self.quit),
        )
        self.icon = pystray.Icon("MediaCatcher", make_icon_image(), "Media Catcher", menu)

        def setup(icon):
            icon.visible = True
            if not load_state().get("welcomed"):  # only once: tells the user where the icon is
                time.sleep(1.5)
                self.notify("Media Catcher is running in the background. Its icon is next to the clock (it may be hidden under the ^ arrow).")
                save_state(welcomed=True)
            if self.auto_update:
                threading.Thread(target=self.auto_update_loop, daemon=True).start()

        self.icon.run(setup)  # returns when the user clicks "Quit"


# ---------------------------------------------------------------- Entry point
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tray", action="store_true", help="server only (no tray icon)")
    ap.add_argument("--no-update", action="store_true", help="disable automatic updates")
    args = ap.parse_args(argv)

    setup_logging()
    if not acquire_single_instance():
        print("Media Catcher is already running.")
        return 0
    if port_busy() and not wait_port_free(15):
        message_box(f"Port {PORT} is used by another program, so Media Catcher cannot start.")
        return 1

    # Automatic updates only in the installed build (it has a python folder), not in a dev environment.
    # Never waited for at startup: it runs in the background and, without internet, fails silently and is retried later.
    auto_update = (APP_DIR / "python").is_dir() and not args.no_update

    print("starting server...")
    try:
        srv = ServerThread()
        srv.start()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        message_box(f"Could not start the local server:\n{e}\n\nDetails: {LOG_FILE}")
        return 1
    print(f"server ready on http://{HOST}:{PORT}")

    use_tray = not args.no_tray
    if use_tray:
        try:
            import pystray  # noqa: F401
        except Exception as e:  # noqa: BLE001
            print("tray unavailable:", e)
            use_tray = False

    quit_from_tray = False
    if use_tray:
        print("starting tray icon...")
        try:
            Controller(srv, auto_update).run_tray()
            quit_from_tray = True  # returned normally = the user clicked "Quit"
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            message_box(f"Could not show the tray icon, but Media Catcher keeps running in the background.\nDetails: {LOG_FILE}")

    if not quit_from_tray:
        try:
            while srv.alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    srv.stop()
    release_single_instance()
    return 0


def run() -> int:
    """Catches any unexpected error so the app never dies silently (pythonw shows nothing when it crashes)."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        tb = traceback.format_exc()
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write("FATAL:\n" + tb + "\n")
        except OSError:
            pass
        message_box("An unexpected error occurred:\n\n" + tb[-700:] + f"\n\nDetails: {LOG_FILE}")
        return 1


if __name__ == "__main__":
    sys.exit(run())
