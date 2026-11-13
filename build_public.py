import json
import tempfile
from pathlib import Path
import app
from demo_data import seed_demo

root = Path(__file__).parent
output = root / 'docs'
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    app.DB = Path(directory) / 'fictional.sqlite3'
    seed_demo(app.connect, app.reconcile)
    with app.connect() as connection:
        state = {table: [dict(row) for row in connection.execute('SELECT * FROM ' + table)] for table in ['imports', 'history', 'mappings', 'companies']}
        state['settings'] = json.loads(connection.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
        state['demo'] = True
    assert len(state['companies']) == 4
    last = json.loads(state['history'][-1]['data'])
    assert last['rows'] == 52
    assert sum(row['status'] == 'Exception' for row in last['results']) == 4

html = (root / 'index.html').read_text()
api_start = html.index('async function api(')
api_end = html.index('\nasync function action(', api_start)
html = html[:api_start] + (root / 'browser_store.js').read_text() + html[api_end:]
html = html.replace('<h2>Imports</h2>', '<h2>Imports</h2><p class="subtitle">Files are processed and saved in this browser. They are not sent to a server. Clearing browser data deletes this workspace.</p>')
html = html.replace('<title>IC Reconciliation</title>', '<title>IC Reconciliation | Intercompany workspace</title><meta name="description" content="Intercompany reconciliation status, company comparisons and difference analysis.">')
(output / 'index.html').write_text(html)
(output / 'state.json').write_text(json.dumps(state, ensure_ascii=False))
(output / '.nojekyll').touch()
print('Public site generated using fictional data only: docs/')
