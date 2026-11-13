import csv
import io
import json
import sqlite3
import uuid
import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).parent
DEMO = False
DB = ROOT / 'reconciliation.sqlite3'
FIELDS = ['entity', 'counterparty', 'account', 'period', 'currency', 'amount', 'reference', 'date']
CATEGORIES = ['Balance', 'P&L', 'Patrimonio']

def conversion_methods(payload):
    methods = payload.get('methods', {category: payload.get('method', 'Closing') for category in CATEGORIES})
    if not isinstance(methods, dict) or set(methods) != set(CATEGORIES) or any(value not in ['Closing', 'Average', 'Historical'] for value in methods.values()):
        raise ValueError('Selecciona un método válido para Balance, P&L y Patrimonio')
    return methods

def connect():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    connection.executescript('''
    CREATE TABLE IF NOT EXISTS mappings (name TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY, name TEXT, created TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, created TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS companies (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
    ''')
    if 'company_id' not in [row['name'] for row in connection.execute('PRAGMA table_info(imports)')]:
        connection.execute('ALTER TABLE imports ADD COLUMN company_id TEXT')
    for system in ['NetSuite', 'Odoo', 'A3']:
        for statement in ['Balance', 'P&L']:
            connection.execute('INSERT OR IGNORE INTO mappings VALUES (?, ?)', (system + '/' + statement, json.dumps(dict(zip(FIELDS, FIELDS)))))
    connection.execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (json.dumps({'mode': 'One Currency', 'base': 'EUR', 'currencies': ['EUR']}),))
    settings = json.loads(connection.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
    settings.setdefault('method', 'Closing')
    settings.setdefault('methods', conversion_methods(settings))
    settings.setdefault('tolerance', '0.01')
    connection.execute('UPDATE settings SET data=? WHERE id=1', (json.dumps(settings),))
    connection.commit()
    return connection

def validate_settings(payload):
    mode = payload.get('mode')
    base = str(payload.get('base', '')).strip().upper()
    currencies = list(dict.fromkeys(str(value).strip().upper() for value in payload.get('currencies', [])))
    if mode not in ['One Currency', 'Multi Currency']:
        raise ValueError('Selecciona One Currency o Multi Currency')
    if not currencies or any(len(value) != 3 or not value.isascii() or not value.isalpha() for value in currencies):
        raise ValueError('Introduce códigos de moneda de tres letras, por ejemplo EUR, USD')
    if base not in currencies:
        raise ValueError('La moneda base debe estar entre las monedas seleccionadas')
    if mode == 'One Currency' and len(currencies) != 1:
        raise ValueError('One Currency requiere una sola moneda')
    if mode == 'Multi Currency' and len(currencies) < 2:
        raise ValueError('Multi Currency requiere al menos dos monedas')
    method = payload.get('method', 'Closing')
    if method not in ['Closing', 'Average', 'Historical']:
        raise ValueError('Método de conversión no válido')
    tolerance = amount(payload.get('tolerance', '0.01'))
    if tolerance < 0:
        raise ValueError('La tolerancia no puede ser negativa')
    return dict(mode=mode, base=base, currencies=currencies, methods=conversion_methods(payload), tolerance=str(tolerance))

def amount(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Importe o tipo de cambio no válido')
    return result

def reconcile(rows, options):
    tolerance = amount(options.get('tolerance', '0.01'))
    if tolerance < 0:
        raise ValueError('La tolerancia debe ser positiva')
    mode = options.get('mode', 'One Currency')
    method = options.get('method', 'Closing')
    matching = options.get('matching', 'Balances')
    if mode not in ['One Currency', 'Multi Currency'] or method not in ['Closing', 'Average', 'Historical'] or matching not in ['Balances', 'Movements']:
        raise ValueError('Configuración no válida')
    base = options.get('base', 'EUR').upper()
    rates = options.get('rates', {})
    groups = {}
    methods = conversion_methods(options)
    for row in rows:
        category = row.get('category') or row['statement']
        if category not in CATEGORIES:
            raise ValueError('Categoría contable desconocida: ' + category)
        method = methods[category]
        entity, counterparty = row['entity'], row['counterparty']
        if entity == counterparty:
            raise ValueError('Una entidad no puede ser su propia contraparte')
        value = amount(row['amount'])
        currency = row['currency'].upper()
        if options.get('currencies') and currency not in options['currencies']:
            raise ValueError('Moneda no configurada en Settings: ' + currency)
        if currency != base:
            if mode == 'One Currency':
                raise ValueError('One Currency exige todos los registros en la divisa base')
            rate_key = '|'.join([currency, row['date'] if method == 'Historical' else row['period'], method])
            if rate_key not in rates:
                raise ValueError('Falta tipo de cambio: ' + rate_key)
            rate = amount(rates[rate_key])
            if rate <= 0:
                raise ValueError('El tipo de cambio debe ser mayor que cero')
            value *= rate
        pair = sorted([entity, counterparty])
        reference = row.get('reference', '') if matching == 'Movements' else ''
        if matching == 'Movements' and not reference:
            raise ValueError('Los movimientos necesitan referencia')
        key = tuple(pair + [row['period'], row['account'], row['statement'], reference, category])
        group = groups.setdefault(key, {'left': [], 'right': [], 'left_total': Decimal(0), 'right_total': Decimal(0)})
        side = 'left' if entity == pair[0] else 'right'
        group[side].append(dict(row, converted=str(value), conversion_method=method if currency != base else None))
        group[side + '_total'] += value
    results = []
    for key, group in groups.items():
        difference = group['left_total'] + group['right_total']
        matched = bool(group['left'] and group['right']) and abs(difference) <= tolerance
        results.append(dict(pair=list(key[:2]), period=key[2], account=key[3], statement=key[4], reference=key[5], category=key[6], status='Matched' if matched else 'Exception', difference=str(difference), **{name: str(value) if isinstance(value, Decimal) else value for name, value in group.items()}))
    return {'options': options, 'results': results, 'rows': len(rows)}

def ingest(payload, mapping):
    company = str(payload.get('company', '')).strip()
    if not company:
        raise ValueError('Selecciona una empresa del listado')
    rows = list(csv.DictReader(io.StringIO(payload['csv'].lstrip('\ufeff'))))
    if not rows:
        raise ValueError('El archivo no contiene registros')
    normalized = []
    for index, source in enumerate(rows, 2):
        row = {field: str(source.get(mapping.get(field, field), '') or '').strip() for field in FIELDS}
        if row['entity'] and row['entity'] != company:
            raise ValueError('Fila %s: la empresa del archivo no coincide con la seleccionada (%s)' % (index, company))
        row['entity'] = company
        for field in FIELDS[:6]:
            if not row[field]:
                raise ValueError('Fila %s: falta %s' % (index, field))
        amount(row['amount'])
        row['statement'] = payload['mapping'].split('/')[1]
        row['category'] = str(source.get(mapping.get('category', 'category'), '') or '').strip() or row['statement']
        if row['category'] not in CATEGORIES or (row['statement'] == 'P&L' and row['category'] != 'P&L') or (row['statement'] == 'Balance' and row['category'] == 'P&L'):
            raise ValueError('Fila %s: categoría incompatible con el estado' % index)
        normalized.append(row)
    return normalized

class Handler(BaseHTTPRequestHandler):
    def reply(self, data, status=200, content_type='application/json'):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type == 'application/json' else data.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/':
            return self.reply((ROOT / 'index.html').read_text(), content_type='text/html')
        if self.path == '/api/state':
            with connect() as connection:
                state = {table: [dict(row) for row in connection.execute('SELECT * FROM ' + table)] for table in ['mappings', 'imports', 'history', 'companies']}
                state['companies'].sort(key=lambda company: company['name'].casefold())
                state['settings'] = json.loads(connection.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
                state['demo'] = DEMO
            return self.reply(state)
        self.reply({'error': 'No encontrado'}, 404)

    def do_POST(self):
        try:
            if self.headers.get('Origin') and self.headers['Origin'] != 'http://' + self.headers.get('Host', ''):
                return self.reply({'error': 'Origen no permitido'}, 403)
            length = int(self.headers.get('Content-Length', 0))
            if length > 20000000:
                raise ValueError('Archivo demasiado grande (máximo 20 MB)')
            payload = json.loads(self.rfile.read(length))
            with connect() as connection:
                if self.path == '/api/company':
                    name = str(payload.get('name', '')).strip()
                    if not name or len(name) > 200:
                        raise ValueError('Introduce un nombre de empresa de 1 a 200 caracteres')
                    if connection.execute('SELECT 1 FROM companies WHERE name=?', (name,)).fetchone():
                        raise ValueError('Esta empresa ya existe en el listado')
                    connection.execute('INSERT INTO companies VALUES (?,?)', (str(uuid.uuid4()), name))
                elif self.path == '/api/settings':
                    settings = validate_settings(payload)
                    connection.execute('UPDATE settings SET data=? WHERE id=1', (json.dumps(settings),))
                elif self.path == '/api/mapping':
                    if not connection.execute('SELECT 1 FROM mappings WHERE name=?', (payload['name'],)).fetchone():
                        raise ValueError('Mapeo desconocido')
                    connection.execute('UPDATE mappings SET data=? WHERE name=?', (json.dumps(payload['data']), payload['name']))
                elif self.path == '/api/import':
                    record = connection.execute('SELECT data FROM mappings WHERE name=?', (payload['mapping'],)).fetchone()
                    if not record:
                        raise ValueError('Mapeo desconocido')
                    company = connection.execute('SELECT * FROM companies WHERE id=?', (payload.get('company_id', ''),)).fetchone()
                    if not company:
                        raise ValueError('Selecciona una empresa configurada en Settings')
                    rows = ingest(dict(payload, company=company['name']), json.loads(record[0]))
                    connection.execute('INSERT INTO imports (id,name,created,data,company_id) VALUES (?,?,?,?,?)', (str(uuid.uuid4()), payload['name'], datetime.now().isoformat(), json.dumps(rows), company['id']))
                elif self.path == '/api/reconcile':
                    selected = payload.get('imports', [])
                    rows = []
                    for record in connection.execute('SELECT * FROM imports'):
                        if record['id'] in selected:
                            rows.extend(json.loads(record['data']))
                    if not rows:
                        raise ValueError('Selecciona al menos una importación')
                    settings = json.loads(connection.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
                    options = dict(payload['options'], **settings)
                    options['matching'] = 'Balances'
                    result = reconcile(rows, options)
                    connection.execute('INSERT INTO history VALUES (?,?,?)', (str(uuid.uuid4()), datetime.now().isoformat(), json.dumps(result)))
                else:
                    return self.reply({'error': 'No encontrado'}, 404)
            self.reply({'ok': True})
        except (ValueError, KeyError, TypeError, InvalidOperation) as error:
            self.reply({'error': str(error)}, 400)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    if args.demo:
        from demo_data import seed_demo
        DEMO = True
        DB = ROOT / 'demo.sqlite3'
        seed_demo(connect, reconcile)
    port = 8766 if DEMO else 8765
    print('IC Reconciliation: http://127.0.0.1:%s' % port, flush=True)
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()
