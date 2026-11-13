const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=fs.readFileSync('docs/index.html','utf8');
assert.ok(html.includes('lang="en"'));
const elements=new Map();
const element=selector=>{if(!elements.has(selector))elements.set(selector,{innerHTML:'',value:'One Currency',textContent:''});return elements.get(selector);};
const context=vm.createContext({Intl,Map,Number,String,JSON,structuredClone,document:{querySelector:element,querySelectorAll:()=>[]}});
vm.runInContext(html.split('<script>')[1].split('</script>')[0].replace('action(refresh);',''),context);
context.fixture=JSON.parse(fs.readFileSync('docs/state.json','utf8'));
for(const tab of ['Dashboard','Imports','Exceptions','History','Mappings','Settings']){
 context.selected=tab;
 vm.runInContext('state=fixture;tab=selected;render();',context);
 const text=element('#main').innerHTML.replace(/<[^>]*>/g,' ');
 assert.ok(!/conciliaci|conciliado|Empresas|Guardar|Patrimonio|Diferencia|Moneda|Importar|registros|atención|método/i.test(text),tab);
 if(tab==='Settings'){assert.ok(text.includes('Equity'));assert.ok(text.includes('Balance Sheet'));}
}
console.log('PASS: all six screens render in English using existing data');
