from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import os
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / 'data' / 'seed.sqlite'
RUNTIME = ROOT / 'data' / 'runtime.sqlite'
MIN_DATE, MAX_DATE = '2026-01-01', '2026-06-17'
INSTANCE = uuid.uuid4().hex
version = 1
auto_phase = 0
alerts: dict[tuple[int, str, int], dict] = {}
clients: set[WebSocket] = set()
lock = asyncio.Lock()
TICK_SECONDS = int(os.environ.get('DASHBOARD_TICK_SECONDS', '15'))

def connect():
    db = sqlite3.connect(RUNTIME, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def check(province: int, date: str):
    try:
        d = dt.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(422, '日期格式应为 YYYY-MM-DD')
    if date < MIN_DATE or date > MAX_DATE or not 1 <= province <= 31:
        raise HTTPException(422, '省份或日期超出演示数据范围')
    return d

def pct(a, b):
    return (a / b * 100) if b else None

def yoy(a, b):
    return ((a - b) / b * 100) if b else None

def metric(current, previous, target, progress):
    r, s = current
    pr, ps = previous
    tr, ts = target
    cr, cs = pct(r, tr), pct(s, ts)
    return {'revenueFen': str(r), 'salesUnits': s, 'revenueTargetFen': str(tr),
            'salesTargetUnits': ts, 'revenueCompletionPct': cr, 'salesCompletionPct': cs,
            'revenueYoyPct': yoy(r, pr), 'salesYoyPct': yoy(s, ps),
            'timeProgressPct': progress, 'revenueGapPp': cr-progress if cr is not None else None,
            'salesGapPp': cs-progress if cs is not None else None,
            'revenuePaceGapFen': str(round(tr*progress/100-r))}

def view(db, province, date):
    d = check(province,date)
    progress = d.timetuple().tm_yday / (366 if calendar.isleap(d.year) else 365) * 100
    start, prev_start, prev_end = f'{d.year}-01-01', f'{d.year-1}-01-01', date.replace(str(d.year),str(d.year-1),1)
    dims = db.execute('SELECT t.id,t.name,t.category_id,c.name AS category FROM dim_product_type t JOIN dim_category c ON c.id=t.category_id ORDER BY t.id').fetchall()
    channels = db.execute('SELECT * FROM dim_channel ORDER BY id').fetchall()
    province_name = db.execute('SELECT name FROM dim_province WHERE id=?',(province,)).fetchone()['name']
    def facts(a,b):
        return {(r['product_type_id'],r['channel_id']):(r['rev'],r['sales']) for r in db.execute('SELECT product_type_id,channel_id,SUM(revenue_fen) rev,SUM(sales_units) sales FROM fact_daily WHERE province_id=? AND biz_date BETWEEN ? AND ? GROUP BY product_type_id,channel_id',(province,a,b))}
    cur, prev = facts(start,date), facts(prev_start,prev_end)
    targets = {(r['product_type_id'],r['channel_id']):(r['rev'],r['sales']) for r in db.execute('SELECT product_type_id,channel_id,SUM(revenue_target_fen) rev,SUM(sales_target_units) sales FROM fact_annual_target WHERE province_id=? AND year=? GROUP BY product_type_id,channel_id',(province,d.year))}
    def aggregate(types=None, channels_filter=None):
        keys = [k for k in targets if (types is None or k[0] in types) and (channels_filter is None or k[1] in channels_filter)]
        def sums(src): return tuple(sum(src.get(k,(0,0))[i] for k in keys) for i in (0,1))
        return metric(sums(cur),sums(prev),sums(targets),progress)
    overall = aggregate()
    cats=[]
    for cid,name in dict((r['category_id'],r['category']) for r in dims).items():
        rows=[r for r in dims if r['category_id']==cid]
        item={'id':cid,'name':name,**aggregate({r['id'] for r in rows})}
        item['children']=[{'id':r['id'],'name':r['name'],**aggregate({r['id']})} for r in rows]
        cats.append(item)
    ch=[]
    for c in channels:
        item={'id':c['id'],'name':c['name'],**aggregate(channels_filter={c['id']})}
        item['sharePct']=pct(int(item['revenueFen']),int(overall['revenueFen']))
        ch.append(item)
    monthly=[{'month':r['month'],'revenueFen':str(r['rev']),'salesUnits':r['sales']} for r in db.execute("SELECT substr(biz_date,1,7) month,SUM(revenue_fen) rev,SUM(sales_units) sales FROM fact_daily WHERE province_id=? AND biz_date BETWEEN ? AND ? GROUP BY month ORDER BY month",(province,start,date))]
    points=[]
    for r in db.execute('SELECT p.id,p.name,p.anchor_city,p.longitude,p.latitude,COALESCE(SUM(f.revenue_fen),0) rev FROM dim_province p LEFT JOIN fact_daily f ON f.province_id=p.id AND f.biz_date BETWEEN ? AND ? GROUP BY p.id ORDER BY p.id',(start,date)):
        points.append({'id':r['id'],'name':r['name'],'city':r['anchor_city'],'lon':r['longitude'],'lat':r['latitude'],'revenueFen':str(r['rev'])})
    valid=[x for x in cats if x['revenueGapPp'] is not None]
    weakest=min(valid,key=lambda x:x['revenueGapPp']) if valid else None
    if weakest:
        gap=weakest['revenueGapPp']
        headline=(f"关注{weakest['name']}：低于时序 {abs(gap):.2f} pp" if gap<0 else '各品类均不低于时序进度')
        evidence=f"{weakest['name']}累计收入 {int(weakest['revenueFen'])/1e10:.2f} 亿元，完成率 {weakest['revenueCompletionPct']:.2f}%，时序差异 {gap:+.2f} pp。"
        diagnosis={'mode':'rule_simulation','headline':headline,'evidence':evidence,'suggestion':'建议进一步核查该品类收入结构及变化。','categoryId':weakest['id']}
    else:
        diagnosis={'mode':'rule_simulation','headline':'数据不足','evidence':'当前无法计算品类时序差异。','suggestion':'请检查演示数据。','categoryId':None}
    active=[a for (p,b,c),a in alerts.items() if p==province and b==date]
    return {'synthetic':True,'instanceId':INSTANCE,'dataVersion':version,'bizDate':date,'province':{'id':province,'name':province_name},'kpis':overall,'categories':cats,'channels':ch,'monthly':monthly,'points':points,'diagnosis':diagnosis,'alerts':active}

async def publish(payload):
    for ws in list(clients):
        try: await ws.send_json(payload)
        except Exception: clients.discard(ws)

def event(kind, **kwargs):
    return {'type':kind,'synthetic':True,'instanceId':INSTANCE,'dataVersion':version,**kwargs}

async def ticker():
    global version,auto_phase
    while True:
        await asyncio.sleep(TICK_SECONDS)
        async with lock:
            db=connect()
            try:
                # 仅演示日期发生周期性可逆模拟修订；锁定告警品类时不改其叶子。
                delta=100_000_000 if auto_phase==0 else -100_000_000
                locked={p for (p,b,c) in alerts if b==MAX_DATE and c==4}
                with db:
                    for p in range(1,32):
                        if p not in locked:
                            db.execute('UPDATE fact_daily SET revenue_fen=revenue_fen+? WHERE biz_date=? AND province_id=? AND product_type_id=8 AND channel_id=4',(delta,MAX_DATE,p))
                auto_phase=1-auto_phase
                version+=1
                e=event('data_changed',bizDate=MAX_DATE,provinceId=None,reason='自动模拟修订')
            finally: db.close()
        await publish(e)

@asynccontextmanager
async def lifespan(app):
    global auto_phase
    if not SEED.exists(): raise RuntimeError('缺少 data/seed.sqlite')
    shutil.copy2(SEED,RUNTIME)
    auto_phase=0
    task=asyncio.create_task(ticker())
    try: yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

app=FastAPI(title='终端经营数据驾驶舱（虚拟演示）',lifespan=lifespan)

@app.get('/api/meta')
async def meta():
    async with lock:
        with closing(connect()) as db:
            provinces=[dict(r) for r in db.execute('SELECT id,name FROM dim_province ORDER BY id')]
        return {'synthetic':True,'instanceId':INSTANCE,'dataVersion':version,'provinces':provinces,'minDate':MIN_DATE,'maxDate':MAX_DATE,'logicalToday':'2026-06-18','tickSeconds':TICK_SECONDS}

@app.get('/api/view')
async def get_view(provinceId:int=19,bizDate:str=MAX_DATE):
    async with lock:
        with closing(connect()) as db: return view(db,provinceId,bizDate)

@app.get('/api/trend')
async def trend(provinceId:int=19,bizDate:str=MAX_DATE,dimension:Literal['category','channel']='category',rowId:int=1):
    d=check(provinceId,bizDate)
    if not 1<=rowId<=4: raise HTTPException(422,'分类不存在')
    where='t.category_id=?' if dimension=='category' else 'f.channel_id=?'
    async with lock:
        with closing(connect()) as db:
            rows=[{'month':r['month'],'revenueFen':str(r['rev'])} for r in db.execute(f"SELECT substr(f.biz_date,1,7) month,SUM(f.revenue_fen) rev FROM fact_daily f JOIN dim_product_type t ON t.id=f.product_type_id WHERE f.province_id=? AND f.biz_date BETWEEN ? AND ? AND {where} GROUP BY month ORDER BY month",(provinceId,f'{d.year}-01-01',bizDate,rowId))]
        return {'dataVersion':version,'instanceId':INSTANCE,'synthetic':True,'monthly':rows}

class Selection(BaseModel):
    provinceId:int=Field(ge=1,le=31)
    bizDate:str=MAX_DATE
    categoryId:int=Field(default=1,ge=1,le=4)

@app.post('/api/demo/trigger-alert')
async def trigger(sel:Selection):
    global version
    d=check(sel.provinceId,sel.bizDate)
    prev=(d-dt.timedelta(days=1)).isoformat()
    key=(sel.provinceId,sel.bizDate,sel.categoryId)
    async with lock:
        if key in alerts: return {'alert':alerts[key],'alreadyTriggered':True,'dataVersion':version}
        db=connect()
        try:
            rows=db.execute('SELECT b.product_type_id,b.channel_id,b.revenue_fen FROM fact_daily b JOIN dim_product_type t ON t.id=b.product_type_id WHERE b.province_id=? AND b.biz_date=? AND t.category_id=?',(sel.provinceId,prev,sel.categoryId)).fetchall()
            today=db.execute('SELECT COUNT(*) FROM fact_daily f JOIN dim_product_type t ON t.id=f.product_type_id WHERE f.province_id=? AND f.biz_date=? AND t.category_id=?',(sel.provinceId,sel.bizDate,sel.categoryId)).fetchone()[0]
            if not rows or len(rows)!=today: raise HTTPException(422,'无完整前日数据，无法触发')
            previous=sum(r['revenue_fen'] for r in rows)
            updated=[((r['revenue_fen']*4+5)//10,sel.provinceId,sel.bizDate,r['product_type_id'],r['channel_id']) for r in rows]
            with db: db.executemany('UPDATE fact_daily SET revenue_fen=? WHERE province_id=? AND biz_date=? AND product_type_id=? AND channel_id=?',updated)
            current=sum(r[0] for r in updated)
            version+=1
            category=db.execute('SELECT name FROM dim_category WHERE id=?',(sel.categoryId,)).fetchone()['name']
            name=db.execute('SELECT name FROM dim_province WHERE id=?',(sel.provinceId,)).fetchone()['name']
            a={'eventId':uuid.uuid4().hex,'provinceId':sel.provinceId,'provinceName':name,'bizDate':sel.bizDate,'categoryId':sel.categoryId,'categoryName':category,'previousFen':str(previous),'currentFen':str(current),'dropPct':(previous-current)/previous*100,'synthetic':True}
            alerts[key]=a
            e=event('alert',provinceId=sel.provinceId,bizDate=sel.bizDate,alert=a)
        finally: db.close()
    await publish(e)
    return {'alert':a,'alreadyTriggered':False,'dataVersion':version}

@app.post('/api/demo/reset')
async def reset():
    global version,auto_phase
    async with lock:
        shutil.copy2(SEED,RUNTIME)
        alerts.clear()
        auto_phase=0
        version+=1
        e=event('reset',reason='演示重置')
    await publish(e)
    return e

class Question(BaseModel):
    provinceId:int=Field(ge=1,le=31)
    bizDate:str=MAX_DATE
    question:str=Field(max_length=200)

@app.post('/api/diagnosis/ask')
async def ask(q:Question):
    async with lock:
        with closing(connect()) as db: data=view(db,q.provinceId,q.bizDate)
        if q.question in ('当前经营情况如何？','当前经营情况如何?'):
            k=data['kpis']; diag=data['diagnosis']
            answer=f"收入完成率 {k['revenueCompletionPct']:.2f}%，时序差异 {k['revenueGapPp']:+.2f} pp。{diag['headline']}。{diag['evidence']}"
        elif q.question in ('为什么触发告警？','为什么触发告警?'):
            if data['alerts']:
                a=data['alerts'][-1]
                answer=f"{a['categoryName']}当日收入 {int(a['currentFen'])/1e6:.2f} 万元，前日 {int(a['previousFen'])/1e6:.2f} 万元，下降 {a['dropPct']:.2f}%，超过 30% 的演示阈值。该规则不能确定业务根因。"
            else: answer='当前没有演示告警。'
        else: answer='目前支持的问题：当前经营情况如何？为什么触发告警？'
        return {'synthetic':True,'mode':'rule_simulation','instanceId':INSTANCE,'dataVersion':version,'answer':answer}

@app.websocket('/api/ws')
async def websocket(ws:WebSocket):
    await ws.accept(); clients.add(ws)
    try:
        await ws.send_json(event('hello'))
        while True:
            message=await ws.receive_text()
            if message=='ping': await ws.send_json(event('pong'))
    except WebSocketDisconnect: pass
    finally: clients.discard(ws)

dist=ROOT/'dist'/'client'
if dist.exists():
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
    app.mount('/data',StaticFiles(directory=dist/'data'),name='data')
    @app.get('/')
    async def index(): return FileResponse(dist/'index.html')
