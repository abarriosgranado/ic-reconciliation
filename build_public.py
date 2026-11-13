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
html = html[:api_start] + '''async function api(path,data){
 if(data||path!=='state')throw Error('Esta versión pública es de consulta.');
 const response=await fetch('./state.json');
 if(!response.ok)throw Error('No se han podido cargar los datos. Recarga la página.');
 return response.json();
}''' + html[api_end:]
html = html.replace("if(tab==='Imports')html+=reconciliationForm(run);", '')
html = html.replace("if(tab==='Settings')currencyFields()}", """if(tab==='Settings')currencyFields();
if(tab==='Imports')document.querySelector('#main .card')?.remove();
document.querySelectorAll('#main button[onclick]').forEach(button=>{
 if(/action\\(/.test(button.getAttribute('onclick')))button.remove();
});
document.querySelectorAll('#main input,#main select,#main textarea').forEach(field=>field.disabled=true);
}""")
html = html.replace('<title>IC Reconciliation</title>', '<title>IC Reconciliation | Intercompany workspace</title><meta name="description" content="Estado de conciliación intercompany, comparación entre empresas y análisis de diferencias.">')
(output / 'index.html').write_text(html)
(output / 'state.json').write_text(json.dumps(state, ensure_ascii=False))
(output / '.nojekyll').touch()
print('Publicación generada únicamente con datos ficticios: docs/')
