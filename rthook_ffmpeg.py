import os
import sys
if getattr(sys, 'frozen', False):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    lib_path = os.path.join(base_path, 'lib')
    if sys.platform == 'darwin' and os.path.isdir(lib_path):
        current_path = os.environ.get('DYLD_LIBRARY_PATH', '')
        if lib_path not in current_path:
            os.environ['DYLD_LIBRARY_PATH'] = f'{lib_path}:{current_path}' if current_path else lib_path
