#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
import threading

def _ensure_app_path() -> None:
    app_dir = os.path.dirname(os.path.abspath(__file__))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

class EarlySplash:

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk
        self._tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.win = tk.Toplevel(self.root)
        self.win.title('YT Downloader')
        self.win.resizable(False, False)
        try:
            self.win.attributes('-topmost', True)
        except Exception:
            pass
        (width, height) = (400, 300)
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.win.geometry(f'{width}x{height}+{x}+{y}')
        frame = tk.Frame(self.win, bg='#f0f0f0')
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text='YT Downloader', font=('Helvetica', 28, 'bold'), fg='#0a84ff', bg='#f0f0f0').pack(pady=(70, 16))
        self._status = tk.Label(frame, text='Spouštím aplikaci…', font=('Helvetica', 14), fg='#666666', bg='#f0f0f0')
        self._status.pack(pady=(8, 16))
        self._bar = ttk.Progressbar(frame, mode='indeterminate', length=220)
        self._bar.pack(pady=12)
        self._bar.start(12)
        self.win.protocol('WM_DELETE_WINDOW', lambda : None)
        self.win.lift()
        self.pump()

    def set_status(self, text: str) -> None:
        try:
            self._status.configure(text=text)
        except Exception:
            pass
        self.pump()

    def pump(self) -> None:
        try:
            self.root.update_idletasks()
            self.win.update()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._bar.stop()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

def run() -> None:
    _ensure_app_path()
    splash = EarlySplash()
    state: dict = {}

    def _load() -> None:
        try:
            import customtkinter
            import downloader_service as ds
            ds.setup_logging()
            import main as app_main
            app_main._ensure_downloader_imports()
            state['main'] = app_main
        except BaseException as exc:
            state['error'] = exc
    threading.Thread(target=_load, name='startup-imports', daemon=True).start()

    def _poll() -> None:
        if 'main' in state or 'error' in state:
            try:
                splash.root.quit()
            except Exception:
                pass
            return
        try:
            splash.root.after(40, _poll)
        except Exception:
            pass
    try:
        splash.root.after(40, _poll)
        splash.root.mainloop()
    except Exception:
        pass
    if 'error' in state:
        splash.close()
        try:
            import tkinter.messagebox as mb
            mb.showerror('YT Downloader', f"Aplikaci se nepodařilo spustit:\n\n{state['error']}")
        except Exception:
            pass
        sys.exit(1)
    app_main = state['main']
    splash.close()
    app_main.main(show_splash=False)
if __name__ == '__main__':
    run()
