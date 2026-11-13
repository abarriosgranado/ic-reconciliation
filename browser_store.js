const storageKey='ic-reconciliation-workspace-v1';
let browserState;
function decimal(value){
 const text=String(value).trim();
 if(!/^[+-]?\d+(\.\d{1,8})?$/.test(text))throw Error('Importe o tipo no válido: '+text+' (máximo 8 decimales)');
 const negative=text.startsWith('-'),parts=text.replace(/^[+-]/,'').split('.');
 return (negative?-1n:1n)*(BigInt(parts[0])*100000000n+BigInt((parts[1]||'').padEnd(8,'0')));
}
function decimalText(value){const negative=value<0n;const absolute=negative?-value:value;return (negative?'-':'')+(absolute/100000000n).toString()+'.'+(absolute%100000000n).toString().padStart(8,'0');}
function csvRows(text){
 text=text.replace(/^\uFEFF/,'');
 const first=text.split(/\r?\n/)[0],separator=first.includes(';')?';':',';
 const rows=[];let row=[],field='',quoted=false;
 for(let index=0;index<text.length;index++){
  const character=text[index];
  if(character==='"'){
   if(quoted&&text[index+1]==='"'){field+='"';index++;}else quoted=!quoted;
  }else if(character===separator&&!quoted){row.push(field);field='';}
  else if((character==='\n'||character==='\r')&&!quoted){if(character==='\r'&&text[index+1]==='\n')index++;row.push(field);if(row.some(value=>value.trim()))rows.push(row);row=[];field='';}
  else field+=character;
 }
 if(quoted)throw Error('CSV con comillas sin cerrar');
 row.push(field);if(row.some(value=>value.trim()))rows.push(row);
 if(rows.length<2)throw Error('El archivo no contiene registros');
 const headers=rows.shift().map(value=>value.trim());
 if(new Set(headers).size!==headers.length)throw Error('Hay columnas duplicadas');
 return rows.map((values,index)=>{if(values.length!==headers.length)throw Error('Número de columnas incorrecto en fila '+(index+2));return Object.fromEntries(headers.map((header,column)=>[header,values[column].trim()]));});
}
function importRows(payload,workspace){
 const company=workspace.companies.find(item=>item.id===payload.company_id);
 const mappingRecord=workspace.mappings.find(item=>item.name===payload.mapping);
 if(!company||!mappingRecord)throw Error('Selecciona empresa y mapeo');
 const mapping=JSON.parse(mappingRecord.data),statement=payload.mapping.split('/')[1];
 return csvRows(payload.csv).map((source,index)=>{
  const row=Object.fromEntries(['entity','counterparty','account','period','currency','amount','reference','date','category'].map(field=>[field,source[mapping[field]||field]||'']));
  if(row.entity&&row.entity!==company.name)throw Error('Fila '+(index+2)+': empresa distinta de la seleccionada');
  row.entity=company.name;row.statement=statement;row.category=row.category||statement;
  for(const field of ['counterparty','account','period','currency','amount'])if(!row[field])throw Error('Fila '+(index+2)+': falta '+field);
  if(!['Balance','P&L','Patrimonio'].includes(row.category)||(statement==='P&L'&&row.category!=='P&L')||(statement==='Balance'&&row.category==='P&L'))throw Error('Categoría incompatible con el estado');
  decimal(row.amount);row.currency=row.currency.toUpperCase();return row;
 });
}
function browserReconcile(rows,options){
 const groups=new Map(),tolerance=decimal(options.tolerance);
 if(tolerance<0n)throw Error('Tolerancia negativa');
 for(const entry of rows){
  const row={...entry},category=row.category||row.statement,method=options.methods[category];
  if(row.entity===row.counterparty)throw Error('Una empresa no puede ser su contraparte');
  if(!options.currencies.includes(row.currency))throw Error('Moneda no configurada: '+row.currency);
  let value=decimal(row.amount);
  if(row.currency!==options.base){
   if(options.mode==='One Currency')throw Error('La moneda debe coincidir con la moneda base');
   const key=[row.currency,method==='Historical'?row.date:row.period,method].join('|');
   if(!options.rates||options.rates[key]===undefined)throw Error('Falta tipo de cambio: '+key);
   const rate=decimal(options.rates[key]);if(rate<=0n)throw Error('Tipo de cambio no válido');
   value=value*rate/100000000n;
  }
  const pair=[row.entity,row.counterparty].sort(),key=JSON.stringify([pair,row.period,row.account,row.statement,category]);
  if(!groups.has(key))groups.set(key,{pair,period:row.period,account:row.account,statement:row.statement,category,reference:'',left:[],right:[],left_total:0n,right_total:0n});
  const group=groups.get(key),side=row.entity===pair[0]?'left':'right';
  group[side].push({...row,converted:decimalText(value),conversion_method:row.currency!==options.base?method:null});group[side+'_total']+=value;
 }
 const results=[...groups.values()].map(group=>{const difference=group.left_total+group.right_total;return {...group,status:group.left.length&&group.right.length&&(difference<0n?-difference:difference)<=tolerance?'Matched':'Exception',difference:decimalText(difference),left_total:decimalText(group.left_total),right_total:decimalText(group.right_total)};});
 return {options,rows:rows.length,results};
}
async function api(path,payload){
 if(!browserState){
  const saved=localStorage.getItem(storageKey);
  if(saved)browserState=JSON.parse(saved);
  else{const response=await fetch('./state.json');if(!response.ok)throw Error('No se han podido cargar los datos');browserState=await response.json();}
 }
 if(path==='state'&&!payload)return structuredClone(browserState);
 const workspace=structuredClone(browserState),created=new Date().toISOString(),id=crypto.randomUUID();
 if(path==='import'){
  const rows=importRows(payload,workspace);
  workspace.imports.push({id,name:payload.name,created,company_id:payload.company_id,data:JSON.stringify(rows)});
 }else if(path==='company'){
  const name=String(payload.name||'').trim();if(!name||name.length>200)throw Error('Nombre de empresa no válido');
  if(workspace.companies.some(item=>item.name.toLowerCase()===name.toLowerCase()))throw Error('La empresa ya existe');
  workspace.companies.push({id,name});
 }else if(path==='mapping'){
  const mapping=workspace.mappings.find(item=>item.name===payload.name);if(!mapping)throw Error('Mapeo desconocido');
  if(!payload.data||typeof payload.data!=='object'||Array.isArray(payload.data)||Object.values(payload.data).some(value=>typeof value!=='string'))throw Error('Mapeo de columnas no válido');
  mapping.data=JSON.stringify(payload.data);
 }else if(path==='settings'){
  const settings=payload;
  if(!['One Currency','Multi Currency'].includes(settings.mode)||!settings.currencies.includes(settings.base)||settings.currencies.some(value=>!(/^[A-Z]{3}$/).test(value))||(settings.mode==='One Currency'?settings.currencies.length!==1:settings.currencies.length<2)||decimal(settings.tolerance)<0n)throw Error('Configuración de monedas no válida');
  if(['Balance','P&L','Patrimonio'].some(category=>!['Closing','Average','Historical'].includes(settings.methods[category])))throw Error('Métodos no válidos');
  workspace.settings=settings;
 }else if(path==='reconcile'){
  const rows=workspace.imports.filter(item=>payload.imports.includes(item.id)).flatMap(item=>JSON.parse(item.data));
  if(!rows.length)throw Error('Selecciona al menos una importación');
  const result=browserReconcile(rows,{...payload.options,...workspace.settings,matching:'Balances'});
  workspace.history.push({id,created,data:JSON.stringify(result)});
 }else throw Error('Operación desconocida');
 try{localStorage.setItem(storageKey,JSON.stringify(workspace));}catch(error){throw Error('No se pudo guardar: el almacenamiento del navegador está lleno o no disponible. No se aplicó el cambio.');}
 browserState=workspace;return {ok:true};
}
