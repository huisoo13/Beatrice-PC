"""Headless app-owned libobs host. The OBS Studio UI is never loaded or launched."""
import argparse
import ctypes as C
import json
import mmap
import os
import sys
import threading
import time
from ctypes import wintypes as W
from pathlib import Path
from .obs_capture import HEADER,OFFSET,CAPACITY


class VideoInfo(C.Structure):
    _fields_=[('graphics_module',C.c_char_p),('fps_num',C.c_uint32),('fps_den',C.c_uint32),
              ('base_width',C.c_uint32),('base_height',C.c_uint32),('output_width',C.c_uint32),
              ('output_height',C.c_uint32),('output_format',C.c_int),('adapter',C.c_uint32),
              ('gpu_conversion',C.c_bool),('colorspace',C.c_int),('range',C.c_int),('scale_type',C.c_int)]

class AudioInfo(C.Structure):
    _fields_=[('samples_per_sec',C.c_uint32),('speakers',C.c_int)]

class VideoData(C.Structure):
    _fields_=[('data',C.POINTER(C.c_ubyte)*8),('linesize',C.c_uint32*8),('timestamp',C.c_uint64)]

VIDEO_CALLBACK=C.CFUNCTYPE(None,C.c_void_p,C.POINTER(VideoData))

def message(text):print(json.dumps(dict(message=text),ensure_ascii=True),flush=True)

def window_settings(client):
    from .game_window import api,client_alive,find_clients
    if not client_alive(client):raise RuntimeError('선택한 게임 창이 종료됐습니다.')
    u=api();u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
    name=C.create_unicode_buffer(256);u.GetClassNameW(client.hwnd,name,256)
    # OBS identifies sources with escaped title:class:executable strings.
    # Prevent its fallback matching from silently targeting another client.
    matches=[c for c in find_clients() if c.title==client.title]
    if len(matches)!=1:raise RuntimeError('OBS 대상 게임 창을 유일하게 구분할 수 없습니다.')
    escape=lambda value:value.replace('#','#22').replace(':','#3A')
    rect=W.RECT();u.GetClientRect(client.hwnd,C.byref(rect))
    width=rect.right-rect.left;height=rect.bottom-rect.top
    if width<=0 or height<=0:raise RuntimeError('OBS 초기 연결 전에 게임 창을 복원해주세요.')
    return dict(capture_mode='window',window=':'.join(map(escape,(client.title,name.value,'lostark.exe'))),
                priority=1,capture_cursor=False,capture_overlays=False,limit_framerate=True,
                anti_cheat_hook=True,capture_audio=False,sli_compatibility=False),width,height

class Engine:
    def __init__(self,runtime,memory):
        self.runtime=runtime;self.memory=memory;self.source=None;self.callback=None
        self.started=False;self.width=0;self.height=0;self.sequence=0;self.last_tick=0
        # OBS uses native LoadLibrary too; make it honor our app-local DLL directory.
        kernel=C.windll.kernel32
        kernel.SetDefaultDllDirectories.argtypes=[W.DWORD];kernel.SetDefaultDllDirectories.restype=W.BOOL
        if not kernel.SetDefaultDllDirectories(0x1000):raise RuntimeError('OBS DLL 검색 경로 초기화 실패')
        self.dll_directory=os.add_dll_directory(str(runtime/'bin/64bit'))
        self.obs=C.CDLL(str(runtime/'bin/64bit/obs.dll'))
        self.bind('obs_startup',C.c_bool,C.c_char_p,C.c_char_p,C.c_void_p)
        self.bind('obs_shutdown',None)
        self.bind('obs_get_version_string',C.c_char_p)
        self.bind('obs_add_data_path',None,C.c_char_p)
        self.bind('obs_reset_video',C.c_int,C.POINTER(VideoInfo))
        self.bind('obs_reset_audio',C.c_bool,C.POINTER(AudioInfo))
        self.bind('obs_open_module',C.c_int,C.POINTER(C.c_void_p),C.c_char_p,C.c_char_p)
        self.bind('obs_init_module',C.c_bool,C.c_void_p)
        self.bind('obs_post_load_modules',None)
        self.bind('obs_data_create_from_json',C.c_void_p,C.c_char_p)
        self.bind('obs_data_release',None,C.c_void_p)
        self.bind('obs_source_create',C.c_void_p,C.c_char_p,C.c_char_p,C.c_void_p,C.c_void_p)
        self.bind('obs_source_release',None,C.c_void_p)
        self.bind('obs_set_output_source',None,C.c_uint32,C.c_void_p)
        self.bind('obs_source_get_width',C.c_uint32,C.c_void_p)
        self.bind('obs_source_get_height',C.c_uint32,C.c_void_p)
        self.bind('obs_add_raw_video_callback',None,C.c_void_p,VIDEO_CALLBACK,C.c_void_p)
        self.bind('obs_remove_raw_video_callback',None,VIDEO_CALLBACK,C.c_void_p)
    def bind(self,name,result,*arguments):
        function=getattr(self.obs,name);function.restype=result;function.argtypes=list(arguments)
    def video(self,width,height):
        if width*height*4>CAPACITY-OFFSET:raise RuntimeError('OBS 지원 프레임 크기를 초과했습니다.')
        info=VideoInfo(str(self.runtime/'bin/64bit/libobs-d3d11.dll').encode('utf-8'),
                       10,1,width,height,width,height,7,0,False,3,2,0)
        result=self.obs.obs_reset_video(C.byref(info))
        if result!=0:raise RuntimeError(f'OBS 영상 초기화 실패 ({result})')
        self.width=width;self.height=height
    def start(self,settings,width,height,test_pattern=False):
        if self.obs.obs_get_version_string().decode()!='32.0.4':raise RuntimeError('OBS ABI 버전 불일치')
        # Vulkan manifests must be absent: stock plugin otherwise registers global layers.
        if list((self.runtime/'data/obs-plugins/win-capture').glob('obs-vulkan*.json')):
            raise RuntimeError('앱 내장 OBS 구성에 전역 Vulkan 설정이 포함되어 있습니다.')
        self.obs.obs_add_data_path(str(self.runtime/'data/libobs').encode('utf-8'))
        if not self.obs.obs_startup(b'ko-KR',None,None):raise RuntimeError('OBS 엔진 초기화 실패')
        self.started=True;self.video(width,height)
        if not self.obs.obs_reset_audio(C.byref(AudioInfo(48000,2))):raise RuntimeError('OBS 초기화 실패')
        module=C.c_void_p()
        plugin='image-source' if test_pattern else 'win-capture'
        result=self.obs.obs_open_module(C.byref(module),str(self.runtime/f'obs-plugins/64bit/{plugin}.dll').encode(),
                                        str(self.runtime/f'data/obs-plugins/{plugin}').encode())
        if result!=0 or not self.obs.obs_init_module(module):raise RuntimeError(f'OBS 캡처 모듈 초기화 실패 ({result})')
        self.obs.obs_post_load_modules()
        data=self.obs.obs_data_create_from_json(json.dumps(settings).encode('utf-8'))
        try:self.source=self.obs.obs_source_create(b'color_source_v3' if test_pattern else b'game_capture',b'Beatrice Game',data,None)
        finally:self.obs.obs_data_release(data)
        if not self.source:raise RuntimeError('OBS 게임 캡처 소스를 만들지 못했습니다.')
        self.obs.obs_set_output_source(0,self.source)
        self.callback=VIDEO_CALLBACK(self.frame)
        self.obs.obs_add_raw_video_callback(None,self.callback,None)
        message('내장 OBS 게임 연결 대기')
    def frame(self,param,frame):
        try:
            width=self.obs.obs_source_get_width(self.source);height=self.obs.obs_source_get_height(self.source)
            if width!=self.width or height!=self.height or not width:return
            video=frame.contents;stride=video.linesize[0];length=stride*height
            if length>CAPACITY-OFFSET or stride<width*4:return
            if video.timestamp<=self.last_tick:return
            pixels=C.string_at(video.data[0],length)
            received=time.monotonic();self.sequence+=2
            header=(self.sequence-1,video.timestamp,received,width,height,stride,1)
            self.memory[:HEADER.size]=HEADER.pack(*header)
            self.memory[OFFSET:OFFSET+length]=pixels
            self.memory[:HEADER.size]=HEADER.pack(self.sequence,*header[1:])
            self.last_tick=video.timestamp
        except Exception as exc:message(f'OBS 프레임 전달 실패: {exc}')
    def resize(self):
        width=self.obs.obs_source_get_width(self.source);height=self.obs.obs_source_get_height(self.source)
        if width and height and (width,height)!=(self.width,self.height):
            self.obs.obs_remove_raw_video_callback(self.callback,None)
            self.memory[:HEADER.size]=HEADER.pack(0,0,0.,0,0,0,0)
            self.video(width,height)
            self.obs.obs_add_raw_video_callback(None,self.callback,None)
    def close(self):
        if self.started:
            if self.callback:self.obs.obs_remove_raw_video_callback(self.callback,None)
            self.obs.obs_set_output_source(0,None)
            if self.source:self.obs.obs_source_release(self.source)
            self.obs.obs_shutdown();self.started=False
        self.dll_directory.close()

def main():
    from .game_window import Client,api,client_alive
    parser=argparse.ArgumentParser();parser.add_argument('--hwnd',type=int,required=True)
    parser.add_argument('--pid',type=int,required=True);parser.add_argument('--memory',required=True)
    parser.add_argument('--runtime',type=Path,required=True);args=parser.parse_args()
    u=api();buffer=C.create_unicode_buffer(1024);u.GetWindowTextW(args.hwnd,buffer,1024)
    client=Client(args.hwnd,args.pid,buffer.value)
    runtime=args.runtime.resolve()
    root=Path(__file__).resolve().parents[1]
    if runtime not in ((root/'obs-runtime').resolve(),(root/'build/obs-runtime').resolve()):
        raise RuntimeError('앱 외부 OBS 엔진 경로는 허용하지 않습니다.')
    try:u.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except (AttributeError,OSError):pass
    settings,width,height=window_settings(client)
    os.chdir(runtime/'bin/64bit')
    memory=mmap.mmap(-1,CAPACITY,tagname=args.memory);engine=None
    stop=threading.Event()
    def commands():
        sys.stdin.read();stop.set()  # EOF when parent closes or exits
    threading.Thread(target=commands,daemon=True).start()
    try:
        engine=Engine(runtime,memory);engine.start(settings,width,height)
        while not stop.wait(.25) and client_alive(client):engine.resize()
    finally:
        if engine is not None:engine.close()
        memory.close()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        message(str(exc))
        import traceback
        traceback.print_exc(file=sys.stderr);sys.exit(1)
