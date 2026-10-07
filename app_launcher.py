"""모델 라이브러리를 import하기 전에 쓰기 가능한 사용자 경로를 설정합니다."""
import os
import sys
from pathlib import Path

def main():
    data=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BeatricePC'
    if '--engine' in sys.argv and os.environ.get('BEATRICE_DATA_DIR'):
        data=Path(os.environ['BEATRICE_DATA_DIR'])
    data.mkdir(parents=True,exist_ok=True)
    os.environ['BEATRICE_DATA_DIR']=str(data)
    for key,folder in [('YOLO_CONFIG_DIR','yolo'),('MPLCONFIGDIR','matplotlib'),('PADDLE_PDX_CACHE_HOME','paddle')]:
        path=data/'cache'/folder;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    os.environ['YOLO_AUTOINSTALL']='false'
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
    if sys.platform=='win32':
        import ctypes
        try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError,OSError):pass
        # pythonw는 표준 스트림이 없으므로 라이브러리 출력도 로그로 보관합니다.
        if '--engine' not in sys.argv:
            stream=(data/'runtime.log').open('a',encoding='utf-8',buffering=1)
            sys.stdout=stream;sys.stderr=stream
    try:
        if '--engine' in sys.argv:
            from beatrice.native_bridge import main as launch
            return launch()
        import subprocess
        root=Path(__file__).resolve().parent
        native=root/'ui/Beatrice.App/bin/x64/Release/net8.0-windows10.0.19041.0/win-x64/BeatricePC.exe'
        packaged=root/'native-ui/BeatricePC.exe'
        executable=packaged if packaged.is_file() else native
        if not executable.is_file():
            raise FileNotFoundError('WinUI 앱을 먼저 빌드해주세요: ui/Beatrice.App/build.ps1')
        subprocess.Popen([str(executable),'--app-root='+str(root)],cwd=root)
        return 0
    except Exception:
        import traceback
        message=traceback.format_exc()
        (data/'startup-error.log').write_text(message,encoding='utf-8')
        if sys.platform=='win32' and '--engine' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,'시작하지 못했습니다. 오류 로그: '+str(data/'startup-error.log'),'Beatrice PC',16)
        elif '--engine' not in sys.argv:raise
        return 1

if __name__=='__main__':sys.exit(main())
