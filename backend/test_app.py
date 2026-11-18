"""API、虚拟数据与推送集成验证；测试使用临时数据库，不修改种子。"""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from fastapi.testclient import TestClient
from backend import app as service

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        service.RUNTIME=Path(cls.tmp.name)/'runtime.sqlite'
        service.TICK_SECONDS=2
        cls.client_context=TestClient(service.app)
        cls.client=cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None,None,None)
        cls.tmp.cleanup()

    def test_complete_flow(self):
        c=self.client
        meta=c.get('/api/meta').json()
        self.assertEqual(len(meta['provinces']),31)
        self.assertEqual(c.get('/api/view',params={'provinceId':99}).status_code,422)
        self.assertEqual(c.post('/api/demo/trigger-alert',json={'provinceId':19,'bizDate':'2026-01-01','categoryId':1}).status_code,422)
        with c.websocket_connect('/api/ws') as ws, c.websocket_connect('/api/ws') as ws2:
            self.assertEqual(ws.receive_json()['type'],'hello')
            self.assertEqual(ws2.receive_json()['type'],'hello')
            before=c.get('/api/view',params={'provinceId':19,'bizDate':'2026-06-17'}).json()
            self.assertEqual(len(before['points']),31)
            self.assertEqual(len(before['categories']),4)
            self.assertEqual(len(before['channels']),4)
            self.assertEqual(len(before['monthly']),6)
            total=int(before['kpis']['revenueFen'])
            self.assertEqual(total,sum(int(x['revenueFen']) for x in before['categories']))
            self.assertEqual(total,sum(int(x['revenueFen']) for x in before['channels']))
            self.assertEqual(total,sum(int(x['revenueFen']) for x in before['monthly']))
            self.assertAlmostEqual(sum(x['sharePct'] for x in before['channels']),100,places=6)
            self.assertAlmostEqual(before['kpis']['timeProgressPct'],168/365*100,places=6)
            auto=ws.receive_json()
            while auto['type']!='data_changed': auto=ws.receive_json()
            self.assertEqual(auto['reason'],'自动模拟修订')
            self.assertGreater(auto['dataVersion'],before['dataVersion'])
            auto2=ws2.receive_json()
            while auto2['type']!='data_changed': auto2=ws2.receive_json()
            self.assertEqual(auto2['dataVersion'],auto['dataVersion'])
            with closing(service.connect()) as db:
                before_rows=[tuple(x) for x in db.execute("SELECT product_type_id,channel_id,revenue_fen,sales_units FROM fact_daily WHERE province_id=19 AND biz_date='2026-06-17' AND product_type_id IN (1,2) ORDER BY 1,2")]
                previous_rows=[tuple(x) for x in db.execute("SELECT product_type_id,channel_id,revenue_fen,sales_units FROM fact_daily WHERE province_id=19 AND biz_date='2026-06-16' AND product_type_id IN (1,2) ORDER BY 1,2")]
                unaffected=[tuple(x) for x in db.execute("SELECT product_type_id,channel_id,revenue_fen,sales_units FROM fact_daily WHERE province_id=19 AND biz_date='2026-06-17' AND product_type_id IN (3,4) ORDER BY 1,2")]
            payload={'provinceId':19,'bizDate':'2026-06-17','categoryId':1}
            result=c.post('/api/demo/trigger-alert',json=payload)
            self.assertEqual(result.status_code,200)
            alert=result.json()['alert']
            self.assertAlmostEqual(alert['dropPct'],60,places=3)
            with closing(service.connect()) as db:
                changed=[tuple(x) for x in db.execute("SELECT product_type_id,channel_id,revenue_fen,sales_units FROM fact_daily WHERE province_id=19 AND biz_date='2026-06-17' AND product_type_id IN (1,2) ORDER BY 1,2")]
                still_unaffected=[tuple(x) for x in db.execute("SELECT product_type_id,channel_id,revenue_fen,sales_units FROM fact_daily WHERE province_id=19 AND biz_date='2026-06-17' AND product_type_id IN (3,4) ORDER BY 1,2")]
            self.assertEqual(unaffected,still_unaffected)
            for old,prior,new in zip(before_rows,previous_rows,changed):
                self.assertEqual(old[:2],new[:2])
                self.assertEqual(old[3],new[3])
                self.assertLessEqual(abs(new[2]-prior[2]*.4),.5)
            self.assertTrue(c.post('/api/demo/trigger-alert',json=payload).json()['alreadyTriggered'])
            msg=ws.receive_json()
            while msg['type']!='alert': msg=ws.receive_json()
            self.assertEqual(msg['alert']['eventId'],alert['eventId'])
            msg2=ws2.receive_json()
            while msg2['type']!='alert': msg2=ws2.receive_json()
            self.assertEqual(msg2['alert']['eventId'],alert['eventId'])
            after=c.get('/api/view',params={'provinceId':19,'bizDate':'2026-06-17'}).json()
            self.assertEqual(after['alerts'][0]['eventId'],alert['eventId'])
            other=c.get('/api/view',params={'provinceId':1,'bizDate':'2026-06-17'}).json()
            self.assertEqual(other['alerts'],[])
            answer=c.post('/api/diagnosis/ask',json={'provinceId':19,'bizDate':'2026-06-17','question':'为什么触发告警？'}).json()
            self.assertIn('60.00%',answer['answer'])
            self.assertIn('不能确定业务根因',answer['answer'])
            trend=c.get('/api/trend',params={'provinceId':19,'bizDate':'2026-06-17','dimension':'category','rowId':1}).json()
            self.assertEqual(len(trend['monthly']),6)
            reset=c.post('/api/demo/reset').json()
            self.assertEqual(reset['type'],'reset')
            after_reset=c.get('/api/view',params={'provinceId':19,'bizDate':'2026-06-17'}).json()
            self.assertEqual(after_reset['alerts'],[])
            self.assertEqual(after_reset['categories'][0]['revenueFen'],before['categories'][0]['revenueFen'])
            self.assertGreater(after_reset['dataVersion'],before['dataVersion'])

if __name__=='__main__':
    unittest.main(verbosity=2)
