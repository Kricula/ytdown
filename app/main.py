#!/usr/bin/env python3
import threading
import queue
import os
import sys
import re
import json
import logging
import customtkinter as ctk
from tkinter import filedialog, messagebox, END, TclError
DownloaderService = None
DownloadOptions = None
ProgressInfo = None
fetch_metadata = None
get_cached_metadata = None
playlist_hint_from_url = None
setup_logging = None
_dl_imports_ready = False

def _ensure_downloader_imports() -> None:
    global DownloaderService, DownloadOptions, ProgressInfo
    global fetch_metadata, get_cached_metadata, playlist_hint_from_url, setup_logging
    global _dl_imports_ready
    if _dl_imports_ready:
        return
    import downloader_service as ds
    DownloaderService = ds.DownloaderService
    DownloadOptions = ds.DownloadOptions
    ProgressInfo = ds.ProgressInfo
    get_cached_metadata = ds.get_cached_metadata
    playlist_hint_from_url = ds.playlist_hint_from_url
    if setup_logging is None:
        setup_logging = ds.setup_logging
    if fetch_metadata is None:
        fetch_metadata = ds.fetch_metadata
    _dl_imports_ready = True
ctk.set_appearance_mode('light')
ctk.set_default_color_theme('blue')
MAX_LOG_LINES = 800
MAX_MSGS_PER_TICK = 200
_SETTINGS_PATH = os.path.expanduser('~/.yt_downloader/settings.json')
_QUALITY_CHOICES = ['Best (MP4 remux)', '1080p (MP4 remux)', '720p (MP4 remux)', 'Audio MP3 (192 kbps)', 'Audio M4A (AAC)']
_DEFAULT_QUALITY = '1080p (MP4 remux)'

def _load_user_settings() -> dict:
    defaults = {'out_dir': os.path.expanduser('~/Downloads'), 'quality': _DEFAULT_QUALITY, 'auto_download': False}
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return defaults
        out_dir = data.get('out_dir')
        if isinstance(out_dir, str) and out_dir.strip():
            defaults['out_dir'] = os.path.expanduser(out_dir.strip())
        quality = data.get('quality')
        if isinstance(quality, str) and quality in _QUALITY_CHOICES:
            defaults['quality'] = quality
        auto_dl = data.get('auto_download')
        if isinstance(auto_dl, bool):
            defaults['auto_download'] = auto_dl
        return defaults
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return defaults

def _save_user_settings(out_dir: str, quality: str, auto_download: bool) -> None:
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        payload = {'out_dir': out_dir, 'quality': quality, 'auto_download': bool(auto_download)}
        with open(_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

class YTDownloaderGUI:

    def __init__(self, root: ctk.CTk, splash=None):
        _ensure_downloader_imports()
        self.root = root
        root.title('YT Downloader')
        root.update_idletasks()
        width = 900
        height = 750
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        root.geometry(f'{width}x{height}+{x}+{y}')
        self.splash = splash
        settings = _load_user_settings()
        default_outdir = settings['out_dir']
        default_quality = settings['quality']
        self.url_var = ctk.StringVar(value='')
        self.quality_var = ctk.StringVar(value=default_quality)
        self.outdir_var = ctk.StringVar(value=default_outdir)
        self.playlist_var = ctk.BooleanVar(value=False)
        self.auto_download_var = ctk.BooleanVar(value=settings['auto_download'])
        frm = ctk.CTkFrame(root, corner_radius=0)
        frm.pack(fill='both', expand=True, padx=20, pady=20)
        self.video_title_label = ctk.CTkLabel(frm, text='', font=ctk.CTkFont(size=16, weight='bold'), text_color='#0a84ff', anchor='w', wraplength=800)
        self.video_title_label.pack(anchor='w', padx=20, pady=(0, 8))
        self.video_status_label = ctk.CTkLabel(frm, text='', font=ctk.CTkFont(size=12), text_color='gray', anchor='w')
        self.video_status_label.pack(anchor='w', padx=20, pady=(0, 16))
        ctk.CTkLabel(frm, text='Video / playlist URL', font=ctk.CTkFont(size=13, weight='normal')).pack(anchor='w', padx=20, pady=(0, 8))
        url_row = ctk.CTkFrame(frm, fg_color='transparent')
        url_row.pack(fill='x', padx=20, pady=(0, 20))
        self.url_entry = ctk.CTkEntry(url_row, textvariable=self.url_var, height=40, font=ctk.CTkFont(size=13))
        self.url_entry.pack(side='left', fill='x', expand=True, padx=(0, 12))
        self.url_var.set('')
        self.url_entry.focus()
        ctk.CTkButton(url_row, text='Paste', command=self._paste_clipboard_url, width=100, height=40).pack(side='left')
        settings_panel = ctk.CTkFrame(frm, corner_radius=10)
        settings_panel.pack(fill='x', padx=20, pady=(0, 20))
        settings_inner = ctk.CTkFrame(settings_panel, fg_color='transparent')
        settings_inner.pack(fill='x', padx=20, pady=20)
        row = ctk.CTkFrame(settings_inner, fg_color='transparent')
        row.pack(fill='x', pady=(0, 16))
        ctk.CTkLabel(row, text='Quality', font=ctk.CTkFont(size=13)).pack(side='left')
        self.quality_var.set(default_quality)
        self.quality_combo = ctk.CTkComboBox(row, values=_QUALITY_CHOICES, variable=self.quality_var, width=300, height=35, font=ctk.CTkFont(size=13))
        self.quality_combo.pack(side='left', padx=(12, 0))
        self.quality_combo.set(default_quality)
        auto_row = ctk.CTkFrame(settings_inner, fg_color='transparent')
        auto_row.pack(fill='x')
        ctk.CTkLabel(auto_row, text='Auto download on URL change', font=ctk.CTkFont(size=13)).pack(side='left')
        self.auto_dl_switch = ctk.CTkSwitch(auto_row, text='', variable=self.auto_download_var, width=50)
        self.auto_dl_switch.pack(side='left', padx=(12, 0))
        row2 = ctk.CTkFrame(frm, fg_color='transparent')
        row2.pack(fill='x', padx=20, pady=(0, 20))
        ctk.CTkLabel(row2, text='Output folder', font=ctk.CTkFont(size=13)).pack(side='left')
        self.outdir_entry = ctk.CTkEntry(row2, textvariable=self.outdir_var, height=40, font=ctk.CTkFont(size=13))
        self.outdir_entry.pack(side='left', fill='x', expand=True, padx=(12, 12))
        self.outdir_var.set(default_outdir)
        ctk.CTkButton(row2, text='Choose…', command=self.choose_dir, width=100, height=40).pack(side='left')
        row3 = ctk.CTkFrame(frm, fg_color='transparent')
        row3.pack(fill='x', padx=20, pady=(0, 20))
        self.download_btn = ctk.CTkButton(row3, text='Download', command=self.on_download, height=45, font=ctk.CTkFont(size=14, weight='bold'))
        self.download_btn.pack(side='left')
        self.stop_btn = ctk.CTkButton(row3, text='Stop', command=self.on_stop, state='disabled', height=45, font=ctk.CTkFont(size=14, weight='bold'), fg_color='gray')
        self.stop_btn.pack(side='left', padx=(12, 0))
        progress_panel = ctk.CTkFrame(frm, corner_radius=10)
        progress_panel.pack(fill='x', padx=20, pady=(0, 20))
        progress_inner = ctk.CTkFrame(progress_panel, fg_color='transparent')
        progress_inner.pack(fill='x', padx=20, pady=20)
        progress_row = ctk.CTkFrame(progress_inner, fg_color='transparent')
        progress_row.pack(fill='x', pady=(0, 12))
        ctk.CTkLabel(progress_row, text='Progress', font=ctk.CTkFont(size=13)).pack(side='left')
        self.progress_label = ctk.CTkLabel(progress_row, text='0%', font=ctk.CTkFont(size=12), text_color='gray')
        self.progress_label.pack(side='left', padx=(12, 0))
        self.log_toggle_btn = ctk.CTkButton(progress_row, text='Log', command=self._toggle_log, width=80, height=30)
        self.progress = ctk.CTkProgressBar(progress_inner, height=20, corner_radius=10)
        self.progress.pack(fill='x')
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(frm, text='', font=ctk.CTkFont(size=16, weight='bold'), text_color='#4caf50')
        self.status_label.pack(anchor='center', padx=20, pady=(0, 20))
        self.log_container = ctk.CTkFrame(frm, corner_radius=10)
        log_inner = ctk.CTkFrame(self.log_container, fg_color='transparent')
        log_inner.pack(fill='both', expand=True, padx=20, pady=20)
        ctk.CTkLabel(log_inner, text='Log', font=ctk.CTkFont(size=13)).pack(anchor='w', pady=(0, 12))
        self.log_text = ctk.CTkTextbox(log_inner, height=200, font=ctk.CTkFont(size=11, family='monospace'))
        self.log_text.pack(fill='both', expand=True)
        self.log_visible = True
        self.msg_q = queue.Queue()
        self.download_thread = None
        self.downloader_service = None
        self.last_clipboard_url = None
        self.title_fetch_token = 0
        self.last_auto_download_url = None
        self._last_seen_url = None
        self._playlist_total_count = 0
        self._playlist_current_index = 0
        self._is_playlist_url = False
        self._meta_request_q = queue.Queue()
        self._meta_debounce_after = None
        self._auto_dl_after = None
        self._meta_worker = threading.Thread(target=self._metadata_worker_loop, daemon=True)
        self._meta_worker.start()
        self.url_var.trace_add('write', self._on_url_change)
        self.quality_var.trace_add('write', lambda *_: self._persist_settings())
        self.outdir_var.trace_add('write', lambda *_: self._persist_settings())
        self.auto_download_var.trace_add('write', lambda *_: self._persist_settings())
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.after(100, self._poll_messages)
        self.root.after(10000, self._check_clipboard_url)
        self.root.after(200, self._refresh_widgets)
        self.root.after(500, self._check_initial_url)

    def _persist_settings(self):
        _save_user_settings(self.outdir_var.get().strip() or os.path.expanduser('~/Downloads'), self.quality_var.get() or _DEFAULT_QUALITY, bool(self.auto_download_var.get()))

    def _on_close(self):
        try:
            self._persist_settings()
        except Exception:
            logging.debug('Uložení nastavení při zavření selhalo', exc_info=True)
        self.root.destroy()

    def _check_initial_url(self):
        current_url = (self.url_var.get() or '').strip()
        if current_url and self._is_youtube_url(current_url):
            self.video_title_label.configure(text='Loading title...', text_color='gray')
            self.video_status_label.configure(text='')
            self._fetch_video_title(current_url)

    def _refresh_widgets(self):
        try:
            current_url = self.url_var.get()
            widget_url = self.url_entry.get()
            if current_url != widget_url:
                self.url_entry.delete(0, 'end')
                if current_url:
                    self.url_entry.insert(0, current_url)
            current_outdir = self.outdir_var.get()
            widget_outdir = self.outdir_entry.get()
            if current_outdir != widget_outdir:
                self.outdir_entry.delete(0, 'end')
                if current_outdir:
                    self.outdir_entry.insert(0, current_outdir)
            current_quality = self.quality_var.get()
            if current_quality != '1080p (MP4 remux)':
                self.quality_var.set('1080p (MP4 remux)')
                self.quality_combo.set('1080p (MP4 remux)')
            self.root.update_idletasks()
        except (TclError, AttributeError) as e:
            logging.debug(f'Widget refresh error (expected during init): {e}')

    @staticmethod
    def _is_youtube_url(text: str) -> bool:
        if not text or not text.strip():
            return False
        text = text.strip().lower()
        youtube_patterns = ['youtube\\.com/watch\\?', 'youtube\\.com/playlist\\?', 'youtu\\.be/', 'youtube\\.com/embed/', 'youtube\\.com/v/', 'youtube\\.com/shorts/']
        return any((re.search(pattern, text) for pattern in youtube_patterns))

    def _reset_url_state(self):
        self._is_playlist_url = False
        self._playlist_total_count = 0
        self._playlist_current_index = 0
        self.title_fetch_token += 1
        self.video_title_label.configure(text='', text_color='#0a84ff')
        self.video_status_label.configure(text='')
        try:
            self.progress.set(0)
            self.progress_label.configure(text='0%')
            self.status_label.configure(text='')
        except (TclError, AttributeError):
            pass

    def _fetch_video_title(self, url: str):
        url = (url or '').strip()
        self.title_fetch_token += 1
        token = self.title_fetch_token
        if not url:
            return
        if self._meta_debounce_after is not None:
            try:
                self.root.after_cancel(self._meta_debounce_after)
            except Exception:
                pass
        self._meta_debounce_after = self.root.after(350, lambda : self._meta_request_q.put((token, url)))

    def _metadata_worker_loop(self):
        while True:
            try:
                (token, url) = self._meta_request_q.get()
            except Exception:
                continue
            if url is None:
                return
            if token != self.title_fetch_token:
                continue
            try:
                meta = fetch_metadata(url, log=self._log)
            except Exception:
                logging.exception('fetch_metadata selhalo pro %s', url)
                meta = None
            if token != self.title_fetch_token:
                continue
            if meta is not None and (meta.title or meta.is_playlist):
                self._is_playlist_url = meta.is_playlist
                self.msg_q.put({'type': 'video_info', 'title': meta.title, 'status': meta.status_text})
            else:
                self.msg_q.put({'type': 'video_info', 'title': '', 'status': ''})

    def _update_video_info(self, title: str, status: str):
        try:
            if title:
                self.video_title_label.configure(text=title, text_color='#0a84ff')
            else:
                self.video_title_label.configure(text='', text_color='#0a84ff')
            if status:
                self.video_status_label.configure(text=status)
            else:
                self.video_status_label.configure(text='')
        except (TclError, AttributeError) as e:
            logging.error(f'Error updating video info: {e}')

    def _paste_clipboard_url(self):
        try:
            clipboard_text = self.root.clipboard_get()
            if clipboard_text and clipboard_text.strip():
                text = clipboard_text.strip()
                if self._is_youtube_url(text):
                    self._reset_url_state()
                    self.msg_q.put({'type': 'update_url', 'url': text})
                    self.last_clipboard_url = text
                    self.video_title_label.configure(text='Loading title...', text_color='gray')
                    self.video_status_label.configure(text='')
                    self._fetch_video_title(text)
                    self._maybe_auto_download(text)
                else:
                    messagebox.showwarning('Invalid URL', 'Clipboard does not contain a valid YouTube URL.\n\nPlease copy a YouTube video or playlist link.')
        except Exception:
            messagebox.showwarning('Clipboard', 'Cannot read from clipboard or clipboard is empty.')

    def _update_url_display(self, text: str):
        try:
            self.url_var.set(text)
            self.url_entry.delete(0, 'end')
            if text:
                self.url_entry.insert(0, text)
            self.root.update_idletasks()
        except (TclError, AttributeError) as e:
            logging.debug(f'URL display update error: {e}')

    def _check_clipboard_url(self):
        try:
            clipboard_text = self.root.clipboard_get()
            if clipboard_text and clipboard_text.strip():
                text = clipboard_text.strip()
                if self._is_youtube_url(text) and text != self.last_clipboard_url:
                    self._reset_url_state()
                    self.msg_q.put({'type': 'update_url', 'url': text})
                    self.last_clipboard_url = text
                    self.video_title_label.configure(text='Loading title...', text_color='gray')
                    self.video_status_label.configure(text='')
                    self._fetch_video_title(text)
                    self._maybe_auto_download(text)
        except (TclError, AttributeError):
            pass
        finally:
            self.root.after(10000, self._check_clipboard_url)

    def _on_url_change(self, *_):
        current = (self.url_var.get() or '').strip()
        if current == self._last_seen_url:
            return
        self._reset_url_state()
        self._last_seen_url = current
        if self._is_youtube_url(current):
            self.video_title_label.configure(text='Loading title...', text_color='gray')
            self.video_status_label.configure(text='')
            self._fetch_video_title(current)
            self._maybe_auto_download(current)

    def _maybe_auto_download(self, url: str):
        if not self.auto_download_var.get():
            return
        url = (url or '').strip()
        if not url or not self._is_youtube_url(url):
            return
        if self._detect_playlist_from_url(url):
            return
        if self.download_thread and self.download_thread.is_alive():
            return
        if url == self.last_auto_download_url:
            return
        try:
            self.url_var.set(url)
            self.url_entry.delete(0, 'end')
            self.url_entry.insert(0, url)
        except (TclError, AttributeError):
            pass
        self.last_auto_download_url = url
        if self._auto_dl_after is not None:
            try:
                self.root.after_cancel(self._auto_dl_after)
            except Exception:
                pass
        self._auto_dl_after = self.root.after(800, self._auto_download_now)

    def _auto_download_now(self):
        self._auto_dl_after = None
        if self.download_thread and self.download_thread.is_alive():
            return
        self.on_download()

    def _toggle_log(self):
        if self.log_visible:
            self.log_container.pack_forget()
            self.log_visible = False
        else:
            padding = {'padx': 10, 'pady': 6}
            self.log_container.pack(fill='both', expand=True, **padding)
            self.log_visible = True

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.outdir_var.get() or os.path.expanduser('~'))
        if d:
            self.outdir_var.set(d)
            self._persist_settings()

    def _reset_progress_ui(self):
        self.progress.set(0)
        self.progress_label.configure(text='0%')
        self.status_label.configure(text='')
        self.log_text.delete('1.0', END)
        self._playlist_current_index = 0
        self._playlist_total_count = 0

    def _set_download_buttons_state(self, downloading: bool):
        if downloading:
            self.download_btn.configure(state='disabled')
            self.stop_btn.configure(state='normal')
        else:
            self.download_btn.configure(state='normal')
            self.stop_btn.configure(state='disabled')

    def _detect_playlist_from_url(self, url: str) -> bool:
        try:
            meta = get_cached_metadata(url)
            if meta is not None:
                return meta.is_playlist
        except Exception:
            pass
        return playlist_hint_from_url(url)

    def on_download(self):
        if self.download_thread and self.download_thread.is_alive():
            logging.info('Stahování už běží – další požadavek ignoruji.')
            return
        try:
            url = self.url_entry.get().strip()
            if url:
                self.url_var.set(url)
        except (TclError, AttributeError):
            url = (self.url_var.get() or '').strip()
        logging.info(f'Download button clicked. URL: {url}')
        if not url:
            messagebox.showwarning('Missing URL', 'Please paste a video or playlist URL.')
            return
        if not self._is_youtube_url(url):
            messagebox.showwarning('Invalid URL', 'Please enter a valid YouTube URL.')
            return
        out_dir = self.outdir_var.get().strip() or os.path.expanduser('~/Downloads')
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                messagebox.showerror('Output folder', f'Cannot create folder:\n{e}')
                return
        is_playlist = self._detect_playlist_from_url(url)
        self._is_playlist_url = is_playlist
        if is_playlist and (not self.video_title_label.cget('text') or self.video_title_label.cget('text') == 'Loading title...'):
            self.video_title_label.configure(text='Loading playlist info...', text_color='gray')
            self.video_status_label.configure(text='')
            self._fetch_video_title(url)
        opts = DownloadOptions(url=url, quality=self.quality_var.get(), out_dir=out_dir, playlist=is_playlist, mp4_default=True)
        self._reset_progress_ui()
        self._log(f"Starting download… (playlist={('Yes' if is_playlist else 'No')})")
        self._set_download_buttons_state(True)
        self.downloader_service = DownloaderService(progress_callback=self._on_progress_update, status_callback=self._on_status_update, log_callback=self._log)
        self.download_thread = threading.Thread(target=self._run_download, args=(opts,), daemon=True)
        self.download_thread.start()

    def on_stop(self):
        if self.downloader_service:
            self.downloader_service.stop()
        self._log('Stop requested. Waiting for current operation to finish…')

    def _on_progress_update(self, info: ProgressInfo):
        self._emit_progress(info.percent)
        if info.playlist_index is not None and info.playlist_total is not None:
            self._playlist_current_index = info.playlist_index
            self._playlist_total_count = info.playlist_total

    def _on_status_update(self, status: str):
        self._emit_status(status)

    def _poll_messages(self):
        processed = 0
        try:
            while processed < MAX_MSGS_PER_TICK:
                msg = self.msg_q.get_nowait()
                processed += 1
                if msg.get('type') == 'log':
                    self._append_log(msg['text'])
                elif msg.get('type') == 'progress':
                    value = msg['value']
                    self.progress.set(value / 100.0)
                    if self._playlist_total_count > 0:
                        progress_text = f'{self._playlist_current_index} z {self._playlist_total_count} - {value:.0f}%'
                    else:
                        progress_text = f'{value:.0f}%'
                    self.progress_label.configure(text=progress_text)
                elif msg.get('type') == 'status':
                    status_text = msg.get('text', '')
                    self.status_label.configure(text=status_text, text_color='#0a84ff')
                elif msg.get('type') == 'done':
                    self.download_btn.configure(state='normal')
                    self.stop_btn.configure(state='disabled')
                elif msg.get('type') == 'completed':
                    if self._playlist_total_count > 0:
                        self.progress_label.configure(text=f'{self._playlist_total_count} z {self._playlist_total_count} - 100%')
                    else:
                        self.progress_label.configure(text='100%')
                    status_text = msg.get('message', 'Download completed successfully')
                    self.status_label.configure(text=status_text, text_color='#4caf50')
                    self._append_log(f'✅ {status_text}')
                elif msg.get('type') == 'error':
                    error_msg = msg.get('message', 'Unknown error')
                    try:
                        messagebox.showerror('Error', error_msg)
                    except Exception as e:
                        logging.error(f'Error showing error dialog: {e}')
                elif msg.get('type') == 'update_url':
                    url_text = msg.get('url', '')
                    self._update_url_display(url_text)
                elif msg.get('type') == 'video_info':
                    title = msg.get('title', '')
                    status = msg.get('status', '')
                    self._update_video_info(title, status)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _log(self, text: str):
        self.msg_q.put({'type': 'log', 'text': text})

    def _append_log(self, text: str):
        self.log_text.insert('end', text + '\n')
        try:
            line_count = int(self.log_text.index('end-1c').split('.')[0])
            if line_count > MAX_LOG_LINES:
                self.log_text.delete('1.0', f'{line_count - MAX_LOG_LINES + 1}.0')
        except (TclError, ValueError, AttributeError):
            logging.debug('Ořez log okna selhal', exc_info=True)
        self.log_text.see('end')

    def _emit_progress(self, value: float):
        self.msg_q.put({'type': 'progress', 'value': max(0.0, min(100.0, value))})

    def _emit_done(self):
        self.msg_q.put({'type': 'done'})

    def _emit_completed(self, message: str):
        self.msg_q.put({'type': 'completed', 'message': message})

    def _emit_status(self, text: str):
        self.msg_q.put({'type': 'status', 'text': text})

    def _update_playlist_counter(self, current: int, total: int):
        self._playlist_current_index = current
        self._playlist_total_count = total

    def _run_download(self, opts: DownloadOptions):
        success = False
        try:
            meta = get_cached_metadata(opts.url)
            if opts.playlist:
                self._log('Starting playlist download...')
                self._emit_status('Starting playlist download...')
            elif meta is not None and meta.title:
                self._log(f'Video title: {meta.title}')
                self._emit_status(f'Starting download: {meta.title}')
            else:
                self._emit_status('Starting download...')
            success = self.downloader_service.download(opts)
            if success:
                self._log('✅ All done.')
                self._emit_progress(100.0)
                self._emit_completed('Download completed successfully')
            elif self.downloader_service and self.downloader_service.stop_requested:
                self._emit_status('Stahování zastaveno')
            else:
                self._log('❌ Stahování se nedokončilo.')
                self._emit_status('Stahování se nedokončilo')
                self.msg_q.put({'type': 'error', 'message': 'Stahování se nedokončilo.\n\nYouTube často mění způsob streamování a bývá potřeba aktuální yt-dlp:\n\n    pip install -U yt-dlp\n\nDetaily jsou v logu: ~/.yt_downloader/downloader.log'})
        except KeyboardInterrupt:
            self._log('⛔️ Download stopped by user.')
            self._emit_status('Download stopped by user')
        except Exception as e:
            error_msg = str(e)
            self._log(f'❌ Error: {error_msg}')
            logging.exception('Download error')
            self._emit_status(f'Error: {error_msg}')
            self.msg_q.put({'type': 'error', 'message': error_msg})
        finally:
            self._playlist_current_index = 0
            self._playlist_total_count = 0
            self._emit_done()

class SplashScreen(ctk.CTkToplevel):

    def __init__(self, master):
        super().__init__(master)
        self.title('YT Downloader')
        (width, height) = (400, 300)
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.geometry(f'{width}x{height}+{x}+{y}')
        self.resizable(False, False)
        try:
            self.attributes('-topmost', True)
        except Exception:
            pass
        frame = ctk.CTkFrame(self, fg_color='transparent')
        frame.pack(fill='both', expand=True)
        ctk.CTkLabel(frame, text='YT Downloader', font=ctk.CTkFont(size=32, weight='bold'), text_color='#0a84ff').pack(pady=(60, 20))
        self._bar = ctk.CTkProgressBar(frame, width=200, height=4, corner_radius=2, mode='indeterminate')
        self._bar.pack(pady=20)
        self._bar.start()
        self._status = ctk.CTkLabel(frame, text='Loading…', font=ctk.CTkFont(size=14), text_color='gray')
        self._status.pack(pady=10)
        self.lift()

    def set_status(self, text: str):
        try:
            self._status.configure(text=text)
        except Exception:
            pass

    def close(self):
        try:
            self._bar.stop()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

def main(show_splash: bool=True):
    _ensure_downloader_imports()
    if setup_logging is not None:
        setup_logging()
    try:
        root = ctk.CTk()
        root.withdraw()
        splash = SplashScreen(root) if show_splash else None
        if splash is not None:
            root.update_idletasks()
            splash.update()
            splash.set_status('Spouštím aplikaci…')
            splash.update()
            splash.set_status('Initializing…')
            splash.update()
        app = YTDownloaderGUI(root, splash)
        _ = app
        if splash is not None:
            splash.set_status('Ready!')
            splash.update()

        def _show_main():
            if splash is not None:
                splash.close()
            try:
                root.deiconify()
                root.lift()
                root.focus_force()
            except Exception:
                pass
        if splash is not None:
            root.after(700, _show_main)
        else:
            root.update_idletasks()
            _show_main()
        root.mainloop()
    except Exception as e:
        import traceback
        error_msg = f'Chyba při spuštění aplikace:\n{e}\n\n{traceback.format_exc()}'
        print(error_msg)
        try:
            import tkinter.messagebox as mb
            mb.showerror('Chyba', error_msg)
        except Exception:
            pass
        sys.exit(1)
if __name__ == '__main__':
    main()
