#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import tempfile
import time
import random
import logging
import threading
import urllib.parse
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any
from yt_dlp import YoutubeDL
_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_LOG_DIR = os.path.expanduser('~/.yt_downloader')
_LOG_FILE = os.path.join(_LOG_DIR, 'downloader.log')
_LOGGING_CONFIGURED = False
logger = logging.getLogger(__name__)

def setup_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(_LOG_FILE, maxBytes=2000000, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass
    _LOGGING_CONFIGURED = True

@dataclass
class DownloadOptions:
    url: str
    quality: str
    out_dir: str
    playlist: bool
    mp4_default: bool = True

@dataclass
class ProgressInfo:
    percent: float
    filename: str
    speed: float
    eta: Optional[int]
    playlist_index: Optional[int] = None
    playlist_total: Optional[int] = None

@dataclass
class VideoMetadata:
    url: str
    title: str = ''
    is_playlist: bool = False
    playlist_count: int = 0
    status_text: str = ''
_METADATA_CACHE: Dict[str, VideoMetadata] = {}
_METADATA_CACHE_LOCK = threading.Lock()
_METADATA_CACHE_MAX = 128
_BOT_HINTS = ('sign in', 'not a bot', 'confirm you', 'cookies', '429', 'too many requests')

def playlist_hint_from_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse((url or '').strip())
        if 'playlist' in parsed.path.lower():
            return True
        qs = urllib.parse.parse_qs(parsed.query)
        return qs.get('list', [None])[0] is not None
    except Exception:
        return False

def get_cached_metadata(url: str) -> Optional[VideoMetadata]:
    with _METADATA_CACHE_LOCK:
        return _METADATA_CACHE.get((url or '').strip())

def clear_metadata_cache() -> None:
    with _METADATA_CACHE_LOCK:
        _METADATA_CACHE.clear()

def _cache_store(url: str, meta: VideoMetadata) -> None:
    with _METADATA_CACHE_LOCK:
        if len(_METADATA_CACHE) >= _METADATA_CACHE_MAX:
            _METADATA_CACHE.clear()
        _METADATA_CACHE[url] = meta

def _count_entries(info: dict) -> int:
    entries = info.get('entries')
    try:
        return len(entries) if entries is not None else 0
    except TypeError:
        return 0

def _extract_info_resilient(url: str, base_opts: Dict[str, Any], log: Optional[Callable[[str], None]]=None):

    def _try(opts):
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False, process=False)
    try:
        info = _try(base_opts)
        if info:
            return info
    except Exception as e:
        msg = str(e).lower()
        if not any((h in msg for h in _BOT_HINTS)):
            if log:
                log(f'Metadata error: {e}')
            return None
        if log:
            log('YouTube vyžaduje ověření – zkouším cookies z prohlížeče…')
    for browser in ('chrome', 'firefox', 'safari', 'edge', 'brave', 'chromium'):
        try:
            info = _try({**base_opts, 'cookiesfrombrowser': (browser,)})
            if info:
                if log:
                    log(f'Metadata načtena přes cookies z {browser}.')
                return info
        except Exception:
            continue
    return None

def fetch_metadata(url: str, use_cache: bool=True, log: Optional[Callable[[str], None]]=None, socket_timeout: int=15) -> Optional[VideoMetadata]:
    url = (url or '').strip()
    if not url:
        return None
    if use_cache:
        cached = get_cached_metadata(url)
        if cached is not None:
            return cached
    base_opts = {'quiet': True, 'no_warnings': True, 'noplaylist': False, 'ignoreerrors': True, 'skip_download': True, 'extract_flat': 'in_playlist', 'socket_timeout': socket_timeout, 'retries': 1}
    info = _extract_info_resilient(url, base_opts, log=log)
    if not info:
        return None
    is_playlist = info.get('_type') == 'playlist' or playlist_hint_from_url(url)
    if is_playlist:
        count = info.get('playlist_count') or info.get('n_entries') or _count_entries(info) or 0
        meta = VideoMetadata(url=url, title=info.get('title') or 'Playlist', is_playlist=True, playlist_count=count, status_text=f'Playlist ({count} videos)' if count else 'Playlist')
    else:
        title = info.get('title') or info.get('fulltitle') or info.get('track') or info.get('alt_title') or ''
        if not title and info.get('id'):
            title = f"Video {info['id']}"
        meta = VideoMetadata(url=url, title=title, is_playlist=False, status_text='Skladba')
    _cache_store(url, meta)
    return meta

class DownloaderService:

    def __init__(self, progress_callback: Optional[Callable[[ProgressInfo], None]]=None, status_callback: Optional[Callable[[str], None]]=None, log_callback: Optional[Callable[[str], None]]=None):
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.log_callback = log_callback
        self.stop_requested = False
        self.ffmpeg_path = self._find_ffmpeg_path()
        self._setup_dyld_for_bundle()
        if self.ffmpeg_path:
            logger.info(f'FFmpeg found at: {self.ffmpeg_path}')
        else:
            logger.warning('FFmpeg not found. Merge may fail.')

    def _log(self, message: str):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def _log_debug(self, message: str):
        logger.debug(message)

    def _setup_dyld_for_bundle(self) -> None:
        if not self.ffmpeg_path:
            return
        if not getattr(sys, 'frozen', False):
            return
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        lib_path = os.path.join(base_path, 'lib')
        if os.path.isdir(lib_path):
            current_dyld = os.environ.get('DYLD_LIBRARY_PATH', '')
            if lib_path not in current_dyld:
                os.environ['DYLD_LIBRARY_PATH'] = f'{lib_path}:{current_dyld}' if current_dyld else lib_path
                self._log(f'Set DYLD_LIBRARY_PATH to include: {lib_path}')

    def _emit_progress(self, info: ProgressInfo):
        if self.progress_callback:
            self.progress_callback(info)

    def _emit_status(self, status: str):
        if self.status_callback:
            self.status_callback(status)

    @staticmethod
    def _find_ffmpeg_path() -> Optional[str]:
        if getattr(sys, 'frozen', False):
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            app_ffmpeg = os.path.join(base_path, 'ffmpeg')
            if os.path.isfile(app_ffmpeg) and os.access(app_ffmpeg, os.X_OK):
                return app_ffmpeg
            internal_ffmpeg = os.path.join(base_path, '_internal', 'ffmpeg')
            if os.path.isfile(internal_ffmpeg) and os.access(internal_ffmpeg, os.X_OK):
                return internal_ffmpeg
            if sys.platform == 'darwin':
                app_bundle = os.path.dirname(os.path.dirname(base_path))
                resources_ffmpeg = os.path.join(app_bundle, 'Resources', 'ffmpeg')
                if os.path.isfile(resources_ffmpeg) and os.access(resources_ffmpeg, os.X_OK):
                    return resources_ffmpeg
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            return ffmpeg_path
        common_paths = ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']
        for path in common_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    @staticmethod
    def _compat_mp4_format(height: Optional[int]=None) -> str:
        h = f'[height<={height}]' if height else ''
        return f'bestvideo{h}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo{h}[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]/best{h}[vcodec^=avc1][acodec^=mp4a]/best{h}[ext=mp4]'

    def _build_ydl_opts(self, opts: DownloadOptions) -> Dict[str, Any]:
        outtmpl = os.path.join(opts.out_dir, '%(title)s.%(ext)s')
        ydl_opts = {'outtmpl': outtmpl, 'progress_hooks': [self._create_progress_hook()], 'noplaylist': not opts.playlist, 'ignoreerrors': True, 'restrictfilenames': False, 'retries': 3, 'socket_timeout': 20, 'concurrent_fragment_downloads': 3, 'postprocessor_hooks': [self._create_postprocessor_hook()], 'postprocessor_args': {'Merger+ffmpeg': ['-movflags', '+faststart'], 'VideoRemuxer+ffmpeg': ['-movflags', '+faststart']}}
        if self.ffmpeg_path:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_path
            self._log(f'Using FFmpeg at: {self.ffmpeg_path}')
        else:
            self._log('⚠️ Warning: FFmpeg not found. Merge may fail.')
        q = opts.quality.lower()
        if '1080' in q:
            ydl_opts['format'] = self._compat_mp4_format(1080)
        elif '720' in q:
            ydl_opts['format'] = self._compat_mp4_format(720)
        elif 'mp3' in q:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
            ydl_opts['merge_output_format'] = None
            return ydl_opts
        elif 'm4a' in q or 'aac' in q:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegAudioConvertor', 'preferredcodec': 'm4a'}]
            ydl_opts['merge_output_format'] = None
            return ydl_opts
        else:
            ydl_opts['format'] = self._compat_mp4_format(None)
        ydl_opts['merge_output_format'] = 'mp4'
        return ydl_opts

    def _create_progress_hook(self):
        playlist_state = {'total': 0, 'current': 0}
        throttle = {'file': None, 'last_pct': None, 'last_ts': 0.0}

        def progress_hook(d: Dict[str, Any]):
            if self.stop_requested:
                raise KeyboardInterrupt('User requested stop.')
            status = d.get('status')
            info = d.get('info_dict') or {}
            is_playlist_item = d.get('playlist') is not None or info.get('_type') == 'playlist' or info.get('playlist_index') is not None or (info.get('playlist_auto_number') is not None)
            if is_playlist_item:
                if playlist_state['total'] == 0:
                    playlist_count = info.get('n_entries') or info.get('playlist_count') or d.get('playlist_count') or 0
                    if playlist_count > 0:
                        playlist_state['total'] = playlist_count
                playlist_index = info.get('playlist_index') or info.get('playlist_auto_number') or d.get('playlist_index')
                if playlist_index is not None and playlist_state['total'] > 0:
                    if playlist_index == 0 and playlist_state['total'] > 0:
                        display_index = 1
                    else:
                        display_index = playlist_index
                    playlist_state['current'] = display_index
            if status == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                pct = downloaded / total * 100.0 if total else 0.0
                speed = d.get('speed') or 0
                eta = d.get('eta')
                filename = d.get('filename') or d.get('_filename') or ''
                if not filename:
                    filename = info.get('title') or info.get('id') or 'Unknown'
                now = time.monotonic()
                is_new_file = throttle['file'] != filename
                if is_new_file:
                    throttle['file'] = filename
                    throttle['last_pct'] = None
                    throttle['last_ts'] = 0.0
                should_emit = throttle['last_pct'] is None or abs(pct - throttle['last_pct']) >= 0.7 or now - throttle['last_ts'] >= 0.15
                log_msg = f'Downloading: {filename} - {pct:.1f}%  speed={self._fmt_bytes(speed)}/s  eta={self._fmt_eta(eta)}'
                self._log_debug(log_msg)
                if should_emit:
                    throttle['last_pct'] = pct
                    throttle['last_ts'] = now
                    status_text = f'{filename} - {pct:.1f}% ({self._fmt_bytes(speed)}/s)'
                    self._emit_status(status_text)
                    progress_info = ProgressInfo(percent=pct, filename=filename, speed=speed, eta=eta, playlist_index=playlist_state['current'] if playlist_state['total'] > 0 else None, playlist_total=playlist_state['total'] if playlist_state['total'] > 0 else None)
                    self._emit_progress(progress_info)
            elif status == 'finished':
                filename = d.get('filename') or d.get('_filename') or ''
                if not filename:
                    filename = info.get('title') or 'Unknown'
                self._log(f'Download finished: {filename}. Processing…')
                self._emit_status(f'{filename} - Processing...')
                progress_info = ProgressInfo(percent=100.0, filename=filename, speed=0, eta=None, playlist_index=playlist_state['current'] if playlist_state['total'] > 0 else None, playlist_total=playlist_state['total'] if playlist_state['total'] > 0 else None)
                self._emit_progress(progress_info)
                throttle['file'] = filename
                throttle['last_pct'] = 100.0
                throttle['last_ts'] = time.monotonic()
                if playlist_state['total'] > 0:
                    self._add_random_pause()
        return progress_hook

    def _add_random_pause(self):
        if self.stop_requested:
            return
        pause_time = random.uniform(2.0, 10.0)
        pause_seconds = int(pause_time)
        pause_ms = int((pause_time - pause_seconds) * 1000)
        self._log(f'⏸️  Pausing {pause_seconds}.{pause_ms:03d}s before next video...')
        self._emit_status(f'Pausing {pause_seconds}s before next video...')
        elapsed = 0.0
        check_interval = 0.5
        while elapsed < pause_time:
            if self.stop_requested:
                self._log('⛔ Pause interrupted by user')
                return
            sleep_time = min(check_interval, pause_time - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time
        self._log(f'▶️  Resuming download...')

    def _create_postprocessor_hook(self):

        def postprocessor_hook(d: Dict[str, Any]):
            status = d.get('status')
            postproc = d.get('postprocessor') or ''
            info = d.get('info_dict') or {}
            if status != 'finished':
                return
            final_pp = {'FFmpegMerger', 'FFmpegVideoRemuxer', 'FFmpegAudioConvertor', 'FFmpegExtractAudio', 'MoveFiles', 'Merger', 'VideoRemuxer', 'AudioConvertor', 'ExtractAudio'}
            if postproc and postproc not in final_pp:
                return
            (filepath, _) = self._pick_existing_path(info, d)
            if not filepath or not os.path.isfile(filepath):
                return
            basename_no_ext = os.path.splitext(os.path.basename(filepath))[0]
            title_raw = basename_no_ext or info.get('title') or ''
            (artist, track) = self._split_artist_title(title_raw)
            if not track:
                track = basename_no_ext
            try:
                self._write_audio_tags(filepath, artist, track)
                self._log(f"Tagged audio: artist='{artist}', title='{track}'")
            except Exception as e:
                self._log(f"Warning: cannot set tags for '{filepath}': {e}")
        return postprocessor_hook

    @staticmethod
    def _split_artist_title(title_raw: str) -> tuple[str, str]:
        if not title_raw:
            return ('', '')
        parts = title_raw.split('-', 1)
        if len(parts) == 2:
            return (parts[0].strip(), parts[1].strip())
        return ('', title_raw.strip())

    @staticmethod
    def _write_audio_tags(filepath: str, artist: str, track: str):
        ext = os.path.splitext(filepath)[1].lower().lstrip('.')
        if ext not in {'mp3', 'm4a', 'mp4', 'aac', 'flac', 'oga', 'ogg', 'opus', 'wav'}:
            return
        if ext == 'mp3':
            try:
                from mutagen.easyid3 import EasyID3
                from mutagen.id3 import ID3NoHeaderError
            except ImportError as e:
                raise RuntimeError(f'mutagen missing or unsupported: {e}')
            try:
                audio = EasyID3(filepath)
            except ID3NoHeaderError:
                audio = EasyID3()
                audio.save(filepath)
                audio = EasyID3(filepath)
            audio['title'] = track
            if artist:
                audio['artist'] = artist
            audio.save()
            return
        if ext in {'m4a', 'mp4', 'aac'}:
            try:
                from mutagen.mp4 import MP4
            except ImportError as e:
                raise RuntimeError(f'mutagen missing or unsupported: {e}')
            audio = MP4(filepath)
            if track:
                audio['©nam'] = [track]
            if artist:
                audio['©ART'] = [artist]
            audio.save(filepath)
            return
        if ext in {'flac', 'oga', 'ogg', 'opus', 'wav'}:
            try:
                import mutagen
            except ImportError as e:
                raise RuntimeError(f'mutagen missing or unsupported: {e}')
            audio = mutagen.File(filepath, easy=True)
            if audio is None:
                raise RuntimeError('unsupported audio format for tagging')
            audio['title'] = track or ''
            if artist:
                audio['artist'] = artist
            audio.save()

    @staticmethod
    def _pick_existing_path(info: dict, data: dict) -> tuple[Optional[str], list]:
        candidates = []
        candidates += [info.get('filepath'), info.get('_filename'), data.get('filepath'), data.get('filename'), data.get('target')]
        for key in ('__files_to_move',):
            if key in data:
                try:
                    for val in data[key]:
                        if isinstance(val, (list, tuple)) and len(val) >= 2:
                            candidates.append(val[1])
                except (TypeError, AttributeError):
                    pass
        for item in info.get('requested_downloads') or []:
            candidates.append(item.get('filepath'))
            candidates.append(item.get('_filename'))
            candidates.append(item.get('filename'))
        title = info.get('title') or ''
        ext = info.get('ext') or info.get('final_ext') or info.get('_final_ext')
        dirname = None
        for path_key in ['filepath', '_filename']:
            if info.get(path_key):
                dirname = os.path.dirname(info[path_key])
                break
        if not dirname and data.get('filepath'):
            dirname = os.path.dirname(data['filepath'])
        if not dirname and data.get('target'):
            dirname = os.path.dirname(data['target'])
        if dirname and title and ext:
            candidates.append(os.path.join(dirname, f'{title}.{ext}'))
        for path in candidates:
            if path and os.path.isfile(path):
                return (path, candidates)
        return (None, candidates)

    @staticmethod
    def _fmt_bytes(n) -> str:
        try:
            n = float(n)
        except (ValueError, TypeError):
            return 'n/a'
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while n >= 1024 and i < len(units) - 1:
            n /= 1024.0
            i += 1
        return f'{n:.1f}{units[i]}'

    @staticmethod
    def _fmt_eta(eta: Optional[int]) -> str:
        if eta is None:
            return '—'
        try:
            eta = int(eta)
        except (ValueError, TypeError):
            return '—'
        (m, s) = divmod(eta, 60)
        (h, m) = divmod(m, 60)
        if h > 0:
            return f'{h:d}:{m:02d}:{s:02d}'
        return f'{m:d}:{s:02d}'

    def download(self, opts: DownloadOptions) -> bool:
        self.stop_requested = False
        try:
            ydl_opts = self._build_ydl_opts(opts)
            self._log(f"Options: playlist={('Yes' if opts.playlist else 'No')}, quality={opts.quality}")
            self._log(f'Output: {opts.out_dir}')
            self._log(f'URL: {opts.url}')
            if not self.ffmpeg_path:
                self._log('⚠️ Warning: FFmpeg not found. Video/audio merge may fail.')
                self._emit_status('Warning: FFmpeg not found - merge may fail')
            else:
                self._log(f'✅ FFmpeg found at: {self.ffmpeg_path}')
            with YoutubeDL(ydl_opts) as ydl:
                self._log('Starting download...')
                retcode = ydl.download([opts.url])
            if retcode:
                self._log('❌ yt-dlp ohlásil chybu – stahování se nedokončilo (viz log výše).')
                self._emit_status('Stahování se nedokončilo')
                return False
            self._log('✅ All done.')
            return True
        except KeyboardInterrupt:
            self._log('⛔️ Download stopped by user.')
            self._emit_status('Download stopped by user')
            return False
        except Exception as e:
            error_msg = str(e)
            self._log(f'❌ Error: {error_msg}')
            logger.exception('Download error')
            self._emit_status(f'Error: {error_msg}')
            return False

    def stop(self):
        self.stop_requested = True
