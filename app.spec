block_cipher = None
import customtkinter
import os
import shutil
import subprocess
ctk_path = os.path.dirname(customtkinter.__file__)
ctk_data = [(ctk_path, 'customtkinter')]
for subdir in ['assets', 'themes', 'windows']:
    subdir_path = os.path.join(ctk_path, subdir)
    if os.path.exists(subdir_path):
        ctk_data.append((subdir_path, f'customtkinter/{subdir}'))

def find_ffmpeg_binaries():
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        common_paths = ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']
        for path in common_paths:
            if os.path.isfile(path):
                ffmpeg_path = path
                break
    if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
        print('⚠️ Warning: FFmpeg not found. Application will work but merge may fail.')
        return []
    if os.path.islink(ffmpeg_path):
        ffmpeg_path = os.path.realpath(ffmpeg_path)
    binaries = [(ffmpeg_path, '.')]
    try:
        result = subprocess.run(['otool', '-L', ffmpeg_path], capture_output=True, text=True, check=True)
        for line in result.stdout.split('\n')[1:]:
            line = line.strip()
            if not line or line.startswith('/System/') or line.startswith('/usr/lib/'):
                continue
            if '(' in line:
                lib_path = line.split('(')[0].strip()
                if (lib_path.startswith('/opt/homebrew/') or lib_path.startswith('/usr/local/')) and os.path.isfile(lib_path):
                    binaries.append((lib_path, 'lib'))
    except Exception as e:
        print(f'⚠️ Warning: Could not get FFmpeg dependencies: {e}')
    return binaries
ffmpeg_binaries = find_ffmpeg_binaries()
a = Analysis(['app/bootstrap.py'], pathex=[], binaries=ffmpeg_binaries, datas=ctk_data + [], hiddenimports=['customtkinter', 'customtkinter.windows', 'customtkinter.windows.widgets', 'darkdetect', 'PIL', 'PIL._tkinter_finder', 'PIL.Image', 'PIL.ImageTk', 'PIL._imaging', 'PIL._imagingtk', 'yt_dlp', 'mutagen', 'mutagen.mp4', 'mutagen.easyid3', 'mutagen.id3', 'queue', 'threading', 'subprocess', 'tempfile', 'main', 'downloader_service', 'bootstrap'], hookspath=[], hooksconfig={}, runtime_hooks=['rthook_ffmpeg.py'], excludes=[], win_no_prefer_redirects=False, win_private_assemblies=False, cipher=block_cipher, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='YT Downloader', debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, disable_windowed_traceback=False, argv_emulation=False, target_arch=None, icon='app/icon.icns', codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, upx_exclude=[], name='YT Downloader')
app = BUNDLE(coll, name='YT Downloader.app', icon='app/icon.icns', bundle_identifier='cz.petr.ytdownloader', info_plist={'NSHighResolutionCapable': True, 'CFBundleShortVersionString': '1.2.0', 'CFBundleVersion': '1.2.0', 'LSMinimumSystemVersion': '10.15', 'NSRequiresAquaSystemAppearance': False, 'NSPrincipalClass': 'NSApplication', 'PyRuntimeLocator': '@executable_path/../Frameworks'})
