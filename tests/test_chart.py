import json
import tempfile
from pathlib import Path
import unittest

from assistant.store import Store
from assistant.models import InputSelection
from assistant.tables import run_chart, read, run_operation
from assistant.workbook_excel import import_workbook


class ChartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state')
        self.task = self.store.create()['id']

    def imported(self, name, text):
        path = self.root / name
        path.write_text(text, encoding='utf-8-sig')
        return self.store.import_file(self.task, path)['id']

    def frame(self, file_id):
        return read(self.store, self.task, InputSelection(file_id=file_id))

    def test_aggregation_and_inline_data(self):
        fid = self.imported('数据.csv', '物料,数量\n螺丝,10\n螺母,20\n螺丝,30\n')
        info = run_chart(self.store, self.task, self.frame(fid), {'chart_type': 'column', 'category': '物料', 'values': ['数量'], 'aggregate': 'sum', 'title': '数量汇总'})
        json.dumps(info['chart'])  # inline chart must be JSON serializable
        self.assertEqual(info['chart']['type'], 'column')
        self.assertEqual(info['chart']['title'], '数量汇总')
        self.assertEqual(info['chart']['category'], '物料')
        self.assertEqual(info['chart']['labels'], ['螺丝', '螺母'])
        self.assertEqual(info['chart']['series'], [{'name': '数量', 'values': [40, 20]}])
        self.assertEqual(info['statistics']['input_rows'], 3)
        self.assertEqual(info['statistics']['output_rows'], 2)
        self.assertEqual(info['name'], '图表.xlsx')
        self.assertIn(info['id'], [o['id'] for o in self.store.get(self.task)['outputs']])

    def test_native_chart_written(self):
        fid = self.imported('数据.csv', '物料,数量\n螺丝,10\n螺母,20\n')
        info = run_chart(self.store, self.task, self.frame(fid), {'chart_type': 'pie', 'category': '物料', 'values': ['数量']})
        path, _ = self.store.resolve_file(self.task, info['id'])
        _, issues = import_workbook(path)
        self.assertTrue(any('图表' in str(i) for i in issues), f'预期含图表 limitation，实际: {issues}')

    def test_validation(self):
        fid = self.imported('数据.csv', '物料,数量\n螺丝,10\n螺母,20\n')
        frame = self.frame(fid)
        with self.assertRaisesRegex(ValueError, '不支持的图表类型'):
            run_chart(self.store, self.task, frame, {'chart_type': 'scatter', 'category': '物料', 'values': ['数量']})
        with self.assertRaisesRegex(ValueError, '饼图需要一个数值字段'):
            run_chart(self.store, self.task, frame, {'chart_type': 'pie', 'category': '物料', 'values': ['数量', '数量']})
        with self.assertRaisesRegex(ValueError, '存在的字段'):
            run_chart(self.store, self.task, frame, {'chart_type': 'bar', 'category': '不存在', 'values': ['数量']})
        with self.assertRaisesRegex(ValueError, '不支持的聚合方式'):
            run_chart(self.store, self.task, frame, {'chart_type': 'bar', 'category': '物料', 'values': ['数量'], 'aggregate': 'median'})

    def test_chart_operation_dispatch(self):
        fid = self.imported('数据.csv', '物料,数量\n螺丝,10\n螺母,20\n螺丝,30\n')
        info = run_operation(self.store, self.task, {'kind': 'chart', 'inputs': [{'file_id': fid}], 'params': {'category': '物料', 'values': ['数量'], 'chart_type': 'bar'}})
        self.assertEqual(info['chart']['series'][0]['values'], [40, 20])
        self.assertEqual(info['statistics']['chart_type'], 'bar')


if __name__ == '__main__':
    unittest.main()
