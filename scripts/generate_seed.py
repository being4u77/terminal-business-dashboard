#!/usr/bin/env python3
"""生成省分画像训练用 SQLite 底表，仅使用 Python 标准库。"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import random
import sqlite3
from pathlib import Path

PROVINCES = ['北京','天津','河北','山西','内蒙古','辽宁','吉林','黑龙江','上海','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','广西','海南','重庆','四川','贵州','云南','西藏','陕西','甘肃','青海','宁夏','新疆']
CAPITALS = [('北京',116.407,39.904),('天津',117.200,39.133),('石家庄',114.514,38.042),('太原',112.549,37.857),('呼和浩特',111.749,40.842),('沈阳',123.432,41.806),('长春',125.324,43.817),('哈尔滨',126.535,45.803),('上海',121.473,31.230),('南京',118.797,32.060),('杭州',120.156,30.274),('合肥',117.228,31.821),('福州',119.297,26.075),('南昌',115.858,28.683),('济南',117.120,36.651),('郑州',113.625,34.746),('武汉',114.305,30.593),('长沙',112.939,28.228),('广州',113.264,23.129),('南宁',108.367,22.817),('海口',110.349,20.017),('重庆',106.552,29.564),('成都',104.066,30.572),('贵阳',106.630,26.648),('昆明',102.833,24.880),('拉萨',91.132,29.660),('西安',108.940,34.342),('兰州',103.834,36.061),('西宁',101.778,36.617),('银川',106.230,38.487),('乌鲁木齐',87.617,43.792)]
TYPES = [('移动终端','手机'),('移动终端','平板'),('数生终端','智能穿戴'),('数生终端','智能摄像头'),('产数终端','工业网关'),('产数终端','行业模组'),('行业定制','定制终端'),('行业定制','专用终端')]
CHANNELS = ['自有渠道','社会渠道','政企渠道','线上渠道']
END_MONTH_DAY = (6, 17)
SEED = 20261118
SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE dim_province(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, anchor_city TEXT NOT NULL, longitude REAL NOT NULL, latitude REAL NOT NULL);
CREATE TABLE dim_category(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE dim_product_type(id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES dim_category(id), name TEXT NOT NULL UNIQUE);
CREATE TABLE dim_channel(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE fact_daily (
 biz_date TEXT NOT NULL, province_id INTEGER NOT NULL REFERENCES dim_province(id),
 product_type_id INTEGER NOT NULL REFERENCES dim_product_type(id), channel_id INTEGER NOT NULL REFERENCES dim_channel(id),
 revenue_fen INTEGER NOT NULL CHECK(revenue_fen>=0), sales_units INTEGER NOT NULL CHECK(sales_units>=0),
 PRIMARY KEY(biz_date,province_id,product_type_id,channel_id));
CREATE TABLE fact_annual_target (
 year INTEGER NOT NULL, province_id INTEGER NOT NULL REFERENCES dim_province(id),
 product_type_id INTEGER NOT NULL REFERENCES dim_product_type(id), channel_id INTEGER NOT NULL REFERENCES dim_channel(id),
 revenue_target_fen INTEGER NOT NULL CHECK(revenue_target_fen>0), sales_target_units INTEGER NOT NULL CHECK(sales_target_units>0),
 PRIMARY KEY(year,province_id,product_type_id,channel_id));
CREATE INDEX idx_daily_province_date ON fact_daily(province_id,biz_date);
CREATE INDEX idx_daily_type_date ON fact_daily(product_type_id,biz_date);
'''

def stable_seed(*values):
    raw = '|'.join(map(str, (SEED,) + values)).encode('utf-8')
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], 'big')

def leaf_base(province_id, type_id, channel_id):
    rng = random.Random(stable_seed('leaf', province_id, type_id, channel_id))
    size = 2.0 if province_id in (9, 10, 11, 15, 19) else 1.0
    type_weight = [3.2,1.1,0.9,0.7,0.55,0.45,0.55,0.35][type_id-1]
    channel_weight = [1.3,1.0,0.7,0.55][channel_id-1]
    revenue = int(2600000 * size * type_weight * channel_weight * rng.uniform(0.85,1.15))
    units = max(1,int(revenue / (rng.uniform(140000, 300000))))
    return revenue, units

def days(year):
    current = dt.date(year,1,1)
    end = dt.date(year,*END_MONTH_DAY)
    while current <= end:
        yield current
        current += dt.timedelta(days=1)

def create_db(path):
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.executemany('INSERT INTO metadata VALUES (?,?)', [
            ('dataset','synthetic'),('seed',str(SEED)),('snapshot_date','2026-06-17'),
            ('logical_today','2026-06-18'),('currency_unit','fen'),('sales_unit','unit'),
            ('note','全部数据为虚拟数据；仅用于实战训练，不代表任何真实经营情况')])
        con.executemany('INSERT INTO dim_province VALUES (?,?,?,?,?)',[(i,name,city,lon,lat) for i,(name,(city,lon,lat)) in enumerate(zip(PROVINCES,CAPITALS),1)])
        categories=list(dict.fromkeys(c for c,_ in TYPES))
        con.executemany('INSERT INTO dim_category VALUES (?,?)',enumerate(categories,1))
        con.executemany('INSERT INTO dim_product_type VALUES (?,?,?)',[(i,categories.index(cat)+1,name) for i,(cat,name) in enumerate(TYPES,1)])
        con.executemany('INSERT INTO dim_channel VALUES (?,?)',enumerate(CHANNELS,1))
        targets=[]
        for year in (2025,2026):
            for p in range(1,len(PROVINCES)+1):
                for t in range(1,len(TYPES)+1):
                    for c in range(1,len(CHANNELS)+1):
                        rev,units=leaf_base(p,t,c)
                        year_factor=1.0 if year==2025 else 1.08
                        targets.append((year,p,t,c,round(rev*365*1.04*year_factor),max(1,round(units*365*1.04*year_factor))))
        con.executemany('INSERT INTO fact_annual_target VALUES (?,?,?,?,?,?)',targets)
        for year in (2025,2026):
            rows=[]
            for date in days(year):
                for p in range(1,len(PROVINCES)+1):
                    for t in range(1,len(TYPES)+1):
                        for c in range(1,len(CHANNELS)+1):
                            rev,units=leaf_base(p,t,c)
                            rng=random.Random(stable_seed(date.isoformat(),p,t,c))
                            # 统一叶子粒度生成，可重复；并非真实业务分布。
                            factor=(1.0 if year==2025 else 1.08)*rng.uniform(0.82,1.18)*(1.08 if date.weekday()<5 else 0.84)
                            rows.append((date.isoformat(),p,t,c,max(0,round(rev*factor)),max(0,round(units*factor))))
                if len(rows)>=20000:
                    con.executemany('INSERT INTO fact_daily VALUES (?,?,?,?,?,?)',rows)
                    rows.clear()
            if rows:
                con.executemany('INSERT INTO fact_daily VALUES (?,?,?,?,?,?)',rows)
        con.commit()
        print('已生成:',path)
        for table in ('dim_province','dim_category','dim_product_type','dim_channel','fact_annual_target','fact_daily'):
            print(table,con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0])
    finally:
        con.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='生成可重复的虚拟经营数据')
    parser.add_argument('--output',type=Path,default=Path(__file__).with_name('省分画像_虚拟底表.sqlite'))
    args=parser.parse_args()
    if args.output.exists():
        parser.error(f'输出文件已存在，为避免覆盖请换一个路径：{args.output}')
    create_db(args.output)
