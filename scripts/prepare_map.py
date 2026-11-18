"""首次安装时从 DataV.GeoAtlas 获取学习交流用地图；不把地图数据纳入仓库。"""
from pathlib import Path
from urllib.request import Request, urlopen
import json
import os
import tempfile

ROOT=Path(__file__).resolve().parent.parent
DEST=ROOT/'public'/'data'/'china.json'
URL='https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json'

def valid(raw):
    value=json.loads(raw)
    return value.get('type')=='FeatureCollection' and len(value.get('features',[]))>=31

if DEST.exists():
    if not valid(DEST.read_bytes()): raise SystemExit('Existing map file is invalid; inspect it before retrying.')
    print('Map already exists; retained.')
else:
    with urlopen(Request(URL,headers={'User-Agent':'terminal-dashboard-learning-demo/1.0'}),timeout=40) as r:
        data=r.read()
    if not valid(data): raise SystemExit('Map data did not pass validation.')
    DEST.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='map-',suffix='.tmp',dir=DEST.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data)
        os.replace(name,DEST)
    finally:
        if os.path.exists(name):os.unlink(name)
    print('Learning map downloaded:',DEST)
