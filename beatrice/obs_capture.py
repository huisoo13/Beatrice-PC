"""App-local libobs game capture, isolated from the recognition process."""
import hashlib
import json
import mmap
import os
import struct
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HEADER=struct.Struct('<QQdIIII')  # sequence, OBS timestamp, delivery clock, dimensions, stride, ready
OFFSET=64
CAPACITY=OFFSET+64*1024*1024
SOURCE_TIMEOUT=2.0
READ_RETRY_GRACE=.25

def runtime_path():
    """Resolve only app-owned paths; never look in Program Files or PATH."""
    for candidate in (ROOT/'obs-runtime',ROOT/'build/obs-runtime'):
        if (candidate/'manifest.json').is_file():return candidate.resolve()
    raise RuntimeError('앱 내장 OBS 엔진이 없습니다. 배포 파일을 확인해주세요.')

def read_frame(memory,last_sequence,diagnostic=None):
    def state(value):
        if diagnostic is not None:diagnostic['state']=value
    header=bytes(memory[:HEADER.size]);sequence,ticks,received,width,height,stride,ready=HEADER.unpack(header)
    if not ready or not sequence:state('not_ready');return None
    if sequence%2:state('writer_busy');return None
    if sequence==last_sequence:state('already_read');return None
    if width<1 or height<1 or stride<width*4 or stride*height>CAPACITY-OFFSET:
        raise RuntimeError('OBS 프레임 크기가 올바르지 않습니다.')
    pixels=bytes(memory[OFFSET:OFFSET+stride*height])
    if bytes(memory[:HEADER.size])!=header:state('copy_race');return None
    state('ready')
    return sequence,ticks,received,width,height,stride,pixels

class ObsCapture:
    def __init__(self,client,data_dir):
        self.client=client;self.data_dir=Path(data_dir)
        self.process=None;self.memory=None;self.retry_at=0;self.last_sequence=0
        self.message='내장 OBS 엔진 연결 중';self.log=None
        self.observed_at=None;self.frame_info={}
        self.last_digest=None;self.changed_at=0;self.received_at=0
        self.status_thread=None
        self.wait_kind='interrupted';self.wait_reason=self.message
        self.source_received_at=None;self.read_wait_since=None;self.read_waits={}

    def _waiting(self,reason,transient=False):
        self.wait_kind='transient' if transient else 'interrupted'
        self.wait_reason=reason
        return None,reason

    def _status(self,process):
        for line in process.stdout:
            if process is not self.process:break
            try:self.message=json.loads(line).get('message',self.message)
            except (ValueError,TypeError):
                if self.log is not None:self.log.write(line.encode('utf-8'))
                if 'could not open process' in line:
                    self.message='OBS 게임 접근 거부 · 앱/게임 실행 권한 또는 게임 보안 차단 확인'
                elif 'inject' in line.lower() and ('failed' in line.lower() or 'error' in line.lower()):
                    self.message='OBS 게임 캡처 연결 실패 · 게임 실행 권한 또는 보안 차단 확인'

    def _start(self):
        runtime=runtime_path()
        manifest=json.loads((runtime/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('version')!='32.0.4':raise RuntimeError('내장 OBS 엔진 버전이 일치하지 않습니다.')
        tag='Local\\BeatriceOBS-'+uuid.uuid4().hex
        self.memory=mmap.mmap(-1,CAPACITY,tagname=tag)
        self.memory[:OFFSET]=bytes(OFFSET)
        self.data_dir.mkdir(parents=True,exist_ok=True)
        self.log=(self.data_dir/'obs-engine.log').open('ab',buffering=0)
        command=[sys.executable,'-m','beatrice.obs_engine','--hwnd',str(self.client.hwnd),
                 '--pid',str(self.client.pid),'--memory',tag,'--runtime',str(runtime)]
        self.process=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=self.log,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
        self.status_thread=threading.Thread(target=self._status,args=(self.process,),daemon=True)
        self.status_thread.start()

    def close(self):
        process=self.process
        if process is not None:
            try:process.stdin.close();process.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):process.kill();process.wait(timeout=3)
            if self.status_thread is not None:self.status_thread.join(timeout=1)
            process.stdout.close();self.process=None
        if self.memory is not None:self.memory.close();self.memory=None
        if self.log is not None:self.log.close();self.log=None
        self.last_sequence=0;self.last_digest=None;self.changed_at=0;self.received_at=0
        self.source_received_at=None;self.read_wait_since=None
        self.wait_kind='interrupted';self.wait_reason='내장 OBS 엔진 연결 중'

    def grab(self):
        from .game_window import client_alive,api
        if not client_alive(self.client):raise RuntimeError('게임 창이 종료됐습니다.')
        now=time.monotonic()
        if self.process is not None and self.process.poll() is not None:
            code=self.process.returncode;self.close();self.retry_at=now+2
            self.message=f'내장 OBS 엔진 재연결 대기 ({code}) · obs-engine.log 확인'
        if self.process is None and now>=self.retry_at:
            try:self._start()
            except Exception as exc:
                self.close();self.message=str(exc);self.retry_at=now+2
        if self.memory is None:return self._waiting(self.message)
        now=time.monotonic()
        diagnostic={}
        result=read_frame(self.memory,self.last_sequence,diagnostic)
        if result is None:
            kind=diagnostic['state'];self.read_waits[kind]=self.read_waits.get(kind,0)+1
            if self.wait_kind in ('ready','transient'):
                if self.read_wait_since is None:self.read_wait_since=now
                # Retry a copy collision even after a long analysis. Only a
                # continuing miss and old source delivery establish an outage.
                if now-self.read_wait_since<READ_RETRY_GRACE or (self.source_received_at is not None and now-self.source_received_at<SOURCE_TIMEOUT):
                    return self._waiting('OBS 새 게임 프레임 대기',transient=True)
                return self._waiting('OBS 프레임 공급 중단 · 새 게임 프레임 대기')
            return self._waiting(self.wait_reason if self.last_sequence else self.message)
        self.read_wait_since=None
        sequence,ticks,received,width,height,stride,pixels=result;self.last_sequence=sequence
        self.source_received_at=received
        if now-received>SOURCE_TIMEOUT:return self._waiting('OBS 프레임 공급 지연 · 새 프레임 대기')
        import numpy as np
        raw=np.frombuffer(pixels,dtype=np.uint8).reshape(height,stride)
        image=raw[:,:width*4].reshape(height,width,4)[:,:,:3].copy()
        if image[::8,::8].max(initial=0)<=2:return self._waiting('OBS 게임 화면 대기 · 검은 프레임')
        digest=hashlib.blake2b(pixels,digest_size=16).digest()
        u=api();minimized=bool(u.IsIconic(self.client.hwnd))
        if minimized and digest==self.last_digest:
            return self._waiting('OBS 최소화 상태 · 변경된 게임 프레임 대기')
        if digest!=self.last_digest:self.changed_at=now;self.last_digest=digest
        # OBS composition timestamps advance even when a game texture is frozen.
        # Conservatively stop counting identical pixels after two seconds.
        if now-self.changed_at>2:return self._waiting('OBS 화면 변화 없음 · 정지 화면 또는 렌더링 중단 대기')
        self.observed_at=datetime.now(timezone.utc);self.received_at=now
        self.wait_kind='ready';self.wait_reason=''
        self.frame_info=dict(source='embedded_obs',sourceTicks=ticks,sequence=sequence,
                            minimized=minimized,
                            foreground=u.GetForegroundWindow()==self.client.hwnd,
                            readWaits=dict(self.read_waits))
        return image,''
