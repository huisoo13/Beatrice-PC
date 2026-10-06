"""Process-local inference settings; model geometry and acceptance rules stay separate."""
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def load_config():
    config=json.loads((ROOT/'config/cpu-inference.json').read_text(encoding='utf-8'))
    for name in ('yoloThreads','ocrThreads'):
        value=config.get(name)
        if type(value) is not int or not 1<=value<=32:
            raise ValueError(f'{name}는 1~32 정수여야 합니다.')
        config[name]=min(value,os.cpu_count() or 1)
    if type(config.get('ocrMkldnn')) is not bool:
        raise ValueError('ocrMkldnn은 boolean이어야 합니다.')
    return config


def configure_yolo_threads(count):
    import torch
    if torch.get_num_threads()!=count:torch.set_num_threads(count)
