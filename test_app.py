import unittest
import tempfile
from pathlib import Path
import app

def row(entity='A', counterparty='B', value='100', currency='EUR'):
    return dict(entity=entity, counterparty=counterparty, amount=value, currency=currency, account='IC', period='2026-10', date='2026-10-01', reference='INV1', statement='Balance')

class ReconciliationTests(unittest.TestCase):
    def test_independent_conversion_methods(self):
        methods = {'Balance': 'Closing', 'P&L': 'Average', 'Patrimonio': 'Historical'}
        rates = {'USD|2026-10|Closing': '0.9', 'USD|2026-10|Average': '0.8', 'USD|2026-10-01|Historical': '0.7'}
        for category, expected in [('Balance', '90.0'), ('P&L', '80.0'), ('Patrimonio', '70.0')]:
            entry = dict(row(currency='USD'), category=category)
            result = app.reconcile([entry], dict(mode='Multi Currency', methods=methods, rates=rates))
            self.assertEqual(result['results'][0]['left_total'], expected)

    def test_import_assigns_selected_company(self):
        payload = {'company': 'Parent', 'mapping': 'NetSuite/Balance', 'csv': 'counterparty,account,period,currency,amount\nSubsidiary,IC,2026-10,EUR,100'}
        self.assertEqual(app.ingest(payload, {})[0]['entity'], 'Parent')

    def test_import_rejects_different_company(self):
        payload = {'company': 'Parent', 'mapping': 'NetSuite/Balance', 'csv': 'entity,counterparty,account,period,currency,amount\nOther,Subsidiary,IC,2026-10,EUR,100'}
        with self.assertRaises(ValueError):
            app.ingest(payload, {})

    def test_import_requires_company(self):
        with self.assertRaises(ValueError):
            app.ingest({'csv': 'counterparty,account,period,currency,amount\nB,IC,2026-10,EUR,100', 'mapping': 'A3/Balance'}, {})

    def test_balances(self):
        result = app.reconcile([row(), row('B','A','-100')], {})
        self.assertEqual(result['results'][0]['status'], 'Matched')

    def test_missing_counterparty(self):
        self.assertEqual(app.reconcile([row(value='0')], {})['results'][0]['status'], 'Exception')

    def test_difference(self):
        self.assertEqual(app.reconcile([row(), row('B','A','-90')], {})['results'][0]['difference'], '10')

    def test_currencies(self):
        for method in ['Closing', 'Average', 'Historical']:
            period = '2026-10-01' if method == 'Historical' else '2026-10'
            result = app.reconcile([row(currency='USD'), row('B','A','-92')], dict(mode='Multi Currency', method=method, rates={'USD|'+period+'|'+method:'0.92'}))
            self.assertEqual(result['results'][0]['status'], 'Matched')

    def test_missing_rate(self):
        with self.assertRaises(ValueError):
            app.reconcile([row(currency='USD')], dict(mode='Multi Currency'))

    def test_one_currency(self):
        with self.assertRaises(ValueError):
            app.reconcile([row(currency='USD')], {})

    def test_movement_reference(self):
        other = row('B','A','-100')
        other['reference'] = 'INV2'
        self.assertEqual(len(app.reconcile([row(),other], dict(matching='Movements'))['results']), 2)

    def test_six_persistent_mappings(self):
        previous = app.DB
        with tempfile.TemporaryDirectory() as directory:
            try:
                app.DB = Path(directory)/'test.db'
                with app.connect() as connection:
                    self.assertEqual(connection.execute('SELECT count(*) FROM mappings').fetchone()[0], 6)
                with app.connect() as connection:
                    self.assertEqual(connection.execute('SELECT count(*) FROM mappings').fetchone()[0], 6)
            finally:
                app.DB = previous

    def test_import_validation(self):
        with self.assertRaises(ValueError):
            app.ingest({'csv':'entity,amount\nA,abc', 'mapping':'A3/Balance'}, {})

if __name__ == '__main__':
    unittest.main()
