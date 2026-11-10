import json, os, time, threading, urllib.parse, urllib.request, urllib.error, sqlite3, hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DATA_DIR=Path(os.environ.get('ATLAS_DATA_DIR',str(ROOT))).resolve()
DATA_DIR.mkdir(parents=True,exist_ok=True)
STATE=DATA_DIR/'state.json'
DB=DATA_DIR/'atlas.db'
MODEL_VERSION='3.0-rc1-experimental'

@contextmanager
def database():
 """Transação curta, com fechamento garantido da conexão SQLite."""
 conn=sqlite3.connect(DB,timeout=20)
 try:
  conn.execute('PRAGMA busy_timeout=20000')
  conn.execute('PRAGMA journal_mode=WAL')
  conn.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
  conn.execute('CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
  with conn:
   yield conn
 finally:
  conn.close()

def journal(kind,payload):
 with database() as conn:
  conn.execute('INSERT INTO ledger(ts,kind,payload) VALUES(?,?,?)',(datetime.now(timezone.utc).isoformat(),kind,json.dumps(payload,ensure_ascii=False)))

SERIES={'DFEDTARU':'Fed - taxa-alvo superior','DGS2':'Treasury 2 anos','DGS10':'Treasury 10 anos','DFII5':'Juro real 5 anos','DFII10':'Juro real 10 anos','T5YIE':'Breakeven 5 anos','T10YIE':'Breakeven 10 anos','VIXCLS':'VIX','CPIAUCSL':'CPI','CPILFESL':'CPI núcleo','PCEPI':'PCE','PCEPILFE':'PCE núcleo','UNRATE':'Desemprego','PAYEMS':'Emprego','ICSA':'Pedidos de auxílio-desemprego','GDPC1':'PIB real','RSAFS':'Varejo'}
DEFAULT={'series':{},'events':[],'auto_events':[],'history':[],'change_history':{'USD':[],'GOLD':[]},'audit_events':[],'session_baselines':{},'last_attempt':None,'last_success':None,'error':None,'last_result':None,'last_checked_series':0,'last_failed_series':0,'last_changed_series':0,'refresh_in_progress':False}
lock=threading.Lock()
def load():
 try:
  with database() as conn:
   row=conn.execute('SELECT payload FROM state WHERE id=1').fetchone()
   if row:return json.loads(row[0])
 except (sqlite3.Error,ValueError) as exc:
  raise RuntimeError('Banco Atlas inválido: '+str(exc)) from exc
 try:return json.loads(STATE.read_text('utf-8'))
 except (OSError,ValueError):return json.loads(json.dumps(DEFAULT))
state=load()
# O processo anterior pode ter terminado durante uma coleta; o estado persistido
# não pode deixar o painel eternamente em "consultando" após reiniciar.
if state.get('refresh_in_progress'):
 state['refresh_in_progress']=False
 state['last_result']='interrompido_por_reinicio'
 state['error']='A consulta anterior foi interrompida por uma reinicialização; será repetida.'
for _k,_v in DEFAULT.items():state.setdefault(_k, json.loads(json.dumps(_v)))
# Migração dos registros da v1.6 para séries independentes, sem inventar medições.
if state.get('history') and not any(state.get('change_history',{}).get(a) for a in ('USD','GOLD')):
 prior={}; state['change_history']={'USD':[],'GOLD':[]}
 for record in state['history']:
  for asset in ('USD','GOLD'):
   value=record.get('scores',{}).get(asset,{}).get('score')
   if asset not in prior or value!=prior[asset]:
    state['change_history'][asset].append({'timestamp':record.get('timestamp'),'score':value,'reason':record.get('reason','migrado_v1.6')})
   prior[asset]=value
def save():
 payload=json.dumps(state,ensure_ascii=False)
 with database() as conn:
  conn.execute('INSERT INTO state(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(payload,))

def get_key():
 key=os.environ.get('FRED_API_KEY','').strip()
 if not key:
  p=ROOT/'.env'
  if p.exists():
   for line in p.read_text('utf-8').splitlines():
    if line.strip().startswith('FRED_API_KEY='):key=line.split('=',1)[1].strip().strip('"\'')
 return key

def fetch_one(sid,key):
 params=urllib.parse.urlencode({'series_id':sid,'api_key':key,'file_type':'json','sort_order':'desc','limit':20})
 req=urllib.request.Request('https://api.stlouisfed.org/fred/series/observations?'+params,headers={'User-Agent':'AtlasMacro/1.0'})
 try:
  with urllib.request.urlopen(req,timeout=22) as response:
   payload=json.load(response)
 except urllib.error.HTTPError as exc:
  # Read the API's explanation without exposing the private API key.
  details=exc.read().decode('utf-8',errors='replace').replace(key,'[CHAVE OCULTA]')
  try:
   info=json.loads(details)
   message=str(info.get('error_message') or info.get('message') or details)
  except (ValueError,TypeError):
   message=details
  message=message.replace(key,'[CHAVE OCULTA]')[:350]
  print(f'FRED {sid}: HTTP {exc.code} - {message}',flush=True)
  raise ValueError(f'HTTP {exc.code}: {message}') from None
 obs=[]
 for o in payload.get('observations',[]):
  try:
   value=float(o['value']);day=datetime.fromisoformat(o['date']).date()
   if isfinite(value) and day<=datetime.now(timezone.utc).date():
    obs.append({'date':day.isoformat(),'value':value})
  except (ValueError,TypeError,KeyError,OverflowError):continue
 # Rejeitar datas duplicadas no retorno, mantendo a primeira observação válida.
 obs.sort(key=lambda row:row['date'],reverse=True)
 obs=list({row['date']:row for row in reversed(obs)}.values())
 obs.sort(key=lambda row:row['date'],reverse=True)
 if not obs:raise ValueError('Sem observações numéricas válidas')
 return {'latest':obs[0],'previous':obs[1] if len(obs)>1 else None,'recent':obs[:10],'fetched_at':datetime.now(timezone.utc).isoformat()}

refresh_lock=threading.Lock()
def refresh():
 if not refresh_lock.acquire(blocking=False):return
 try:
  with lock:
   state['refresh_in_progress']=True
   save()
  _refresh_inner()
 except Exception as exc:
  with lock:
   state['last_result']='erro_interno'
   state['error']='Erro interno na consulta: '+str(exc)[:300]
   save()
  print('Atlas refresh error:',str(exc),flush=True)
 finally:
  with lock:
   state['refresh_in_progress']=False
   save()
  refresh_lock.release()
def _refresh_inner():
 key=get_key()
 with lock:state['last_attempt']=datetime.now(timezone.utc).isoformat();state['error']=None;save()
 if not key:
  with lock:state['error']='Configure FRED_API_KEY no arquivo .env';state['last_result']='falha';save()
  return
 failures=[];good=0;detected=[];changed_series=set();updates={}
 # All HTTP requests finish before a single consistent state publication.
 for sid in SERIES:
  try:
   updates[sid]=fetch_one(sid,key)
   good+=1
  except Exception as exc:failures.append(f'{sid}: {str(exc)[:130]}')
 with lock:
  for sid,val in updates.items():
   old=state['series'].get(sid)
   val['first_seen_at']=(old.get('first_seen_at') or old.get('fetched_at')) if old else val['fetched_at']
   if old:
    prior={o['date']:o['value'] for o in old.get('recent',[])}
    current={o['date']:o['value'] for o in val.get('recent',[])}
    for date,new_value in sorted(current.items()):
     if date not in prior and date<=old.get('latest',{}).get('date'):continue
     if date in prior and prior[date]==new_value:continue
     kind='revisao_detectada' if date in prior else 'nova_observacao_detectada'
     changed_series.add(sid)
     detected.append({'id':f'{sid}@{date}@{new_value}','series_id':sid,'series_name':SERIES[sid],
      'observation_date':date,'detected_at':datetime.now(timezone.utc).isoformat(),
      'previous_value':prior.get(date),'new_value':new_value,'kind':kind,
      'impact':'incluído no recálculo quando elegível; sem ajuste adicional',
      'release_time_verified':False,'eligible':True,
      'note':'Detecção na coleta FRED; não representa o horário oficial de divulgação.'})
  state['series'].update(updates)
  if good:state['last_success']=datetime.now(timezone.utc).isoformat()
  state['last_checked_series']=good
  state['last_failed_series']=len(failures)
  state['last_changed_series']=len(changed_series)
  state['last_result']=('falha' if not good else 'parcial' if failures else 'alteracoes' if changed_series else 'sem_alteracoes')
  state['error']=' | '.join(failures) if failures else None
  existing={e['id'] for e in state['auto_events']}
  new_events=[e for e in detected if e['id'] not in existing]
  state['auto_events'].extend(new_events)
  if good:snapshot(reason='fred_refresh',economic_events=new_events)
  save()
 if detected:journal('fred_observations',detected)

def worker():
 next_refresh=0
 while True:
  try:
   if time.monotonic()>=next_refresh:
    # Agendar a próxima tentativa mesmo se uma consulta falhar.
    next_refresh=time.monotonic()+900
    refresh()
   with lock:
    snapshot(reason='time_recalculation')
  except Exception as exc:
   # Falha pontual de cálculo ou disco não deve matar o monitor para sempre.
   print('Atlas worker error:',type(exc).__name__,str(exc)[:250],flush=True)
  time.sleep(60)

# v2.1: exploratory scoring, freshness checks and auditable snapshots.
from zoneinfo import ZoneInfo
from datetime import timedelta
from copy import deepcopy
from math import isfinite
BRASILIA=ZoneInfo('America/Sao_Paulo')
FRESH_DAYS={'DFEDTARU':45,'DGS2':7,'DGS10':7,'DFII5':7,'DFII10':7,'T5YIE':7,'T10YIE':7,'VIXCLS':7,'CPIAUCSL':75,'CPILFESL':75,'PCEPI':85,'PCEPILFE':85,'UNRATE':55,'PAYEMS':55,'ICSA':18,'GDPC1':130,'RSAFS':75}
WEIGHTS_USD={'Juros/Fed':35,'Inflação':20,'Emprego':20,'Atividade':15,'Condições financeiras':10}
WEIGHTS_GOLD={'Juros reais':40,'Condições USD':25,'Inflação implícita':20,'Risco global':15}
# Frequência esperada da série; não equivale a confirmação de publicação oficial.
CADENCE={'DFEDTARU':'por decisão do Fed','DGS2':'diária (dias úteis)','DGS10':'diária (dias úteis)','DFII5':'diária (dias úteis)','DFII10':'diária (dias úteis)','T5YIE':'diária (dias úteis)','T10YIE':'diária (dias úteis)','VIXCLS':'diária (dias úteis)','CPIAUCSL':'mensal','CPILFESL':'mensal','PCEPI':'mensal','PCEPILFE':'mensal','UNRATE':'mensal','PAYEMS':'mensal','ICSA':'semanal','GDPC1':'trimestral','RSAFS':'mensal'}

def session_start(now=None):
 now=(now or datetime.now(timezone.utc)).astimezone(BRASILIA)
 start=now.replace(hour=4,minute=0,second=0,microsecond=0)
 if now<start:start-=timedelta(days=1)
 return start

def observation(sid,asof=None):
 obj=state.get('series',{}).get(sid)
 if not obj:return None
 try:
  fetched=datetime.fromisoformat(obj['fetched_at'])
  latest=obj['latest']; day=datetime.fromisoformat(latest['date']).date()
  now=asof or datetime.now(timezone.utc)
  # Observation dates are not release timestamps. Reject future dates, but do
  # not infer that an observation was published at midnight on its date.
  if fetched.tzinfo is None:fetched=fetched.replace(tzinfo=timezone.utc)
  if fetched>now or day>now.date():return None
  # O dado só pode ser usado a partir da primeira coleta efetivamente registrada.
  first_seen=obj.get('first_seen_at',obj['fetched_at'])
  first_seen_dt=datetime.fromisoformat(first_seen)
  if first_seen_dt.tzinfo is None:first_seen_dt=first_seen_dt.replace(tzinfo=timezone.utc)
  if first_seen_dt>now:return None
  if (now.date()-day).days>FRESH_DAYS[sid]:return None
  if (now-fetched).total_seconds()>86400*2:return None
  recent=[o for o in obj.get('recent',[]) if o.get('date')<=latest['date']]
  if len(recent)<2:return None
  if any(not isfinite(float(o['value'])) for o in recent[:2]):return None
  if recent[0]['date']<=recent[1]['date']:return None
  if recent[0]['date']!=latest['date'] or float(recent[0]['value'])!=float(latest['value']):return None
  return recent
 except (KeyError,ValueError,TypeError,OverflowError):return None

def change(sid):
 o=observation(sid)
 return o[0]['value']-o[1]['value'] if o else None

def change_pct(sid):
 o=observation(sid)
 if not o or not o[1]['value']:return None
 return 100*(o[0]['value']/o[1]['value']-1)

def score(x,scale):
 if x is None or not isfinite(x):return None
 return max(-100,min(100,round(x/scale*50)))

def mean(*values):
 valid=[v for v in values if v is not None]
 return round(sum(valid)/len(valid)) if valid else None

# Cobertura mínima experimental por grupo. Não é validação estatística.
GROUP_MIN={'Juros/Fed':2,'Emprego':2,'Atividade':2,'Juros reais':2,'Condições USD':2,'Inflação implícita':2}
GROUP_METRICS={
 'Juros/Fed':[('DGS2','delta',.10,1),('DGS10','delta',.10,1)],
 'Emprego':[('PAYEMS','delta',250,1),('UNRATE','delta',.15,-1),('ICSA','delta',15000,-1)],
 'Atividade':[('GDPC1','pct',.6,1),('RSAFS','pct',1.0,1)],
 'Juros reais':[('DFII5','delta',.10,-1),('DFII10','delta',.10,-1)],
 'Condições USD':[('DGS2','delta',.10,-1),('DGS10','delta',.10,-1)],
 'Inflação implícita':[('T5YIE','delta',.10,1),('T10YIE','delta',.10,1)]
}
def metric_detail(group):
 rows=[]
 for sid,kind,scale,direction in GROUP_METRICS.get(group,[]):
  obs=observation(sid)
  delta=(obs[0]['value']-obs[1]['value']) if obs else None
  value=(100*(obs[0]['value']/obs[1]['value']-1) if obs and obs[1]['value'] else None) if kind=='pct' else delta
  rows.append({'series_id':sid,'latest':obs[0]['value'] if obs else None,
   'previous':obs[1]['value'] if obs else None,'change':round(value,5) if value is not None else None,
   'unit':'%' if kind=='pct' else 'p.p.' if sid in ('DGS2','DGS10','DFII5','DFII10','T5YIE','T10YIE','UNRATE') else 'unidades',
   'score':score(direction*value,scale) if value is not None else None})
 return rows

def calc():
 # Níveis de inflação não são surpresas; risco global isolado não é sinal direcional.
 def group_value(group):
  rows=metric_detail(group)
  vals=[r['score'] for r in rows if r['score'] is not None]
  return round(sum(vals)/len(vals)) if len(vals)>=GROUP_MIN[group] else None
 usd={'Juros/Fed':group_value('Juros/Fed'),'Inflação':None,
      'Emprego':group_value('Emprego'),'Atividade':group_value('Atividade'),
      'Condições financeiras':None}
 gold={'Juros reais':group_value('Juros reais'),'Condições USD':group_value('Condições USD'),
       'Inflação implícita':group_value('Inflação implícita'),'Risco global':None}
 now=datetime.now(timezone.utc); start=session_start(now).astimezone(timezone.utc)
 adjustments={'USD':0,'GOLD':0};seen=set()
 for event in state.get('events',[]):
  try:
   timestamp=datetime.fromisoformat(event['created_at'])
   if timestamp.tzinfo is None:timestamp=timestamp.replace(tzinfo=timezone.utc)
   if not(start<=timestamp<=now):continue
   eid=str(event.get('event_id') or event.get('id') or (event.get('title',''),timestamp.isoformat()))
   if eid in seen:continue
   seen.add(eid)
   for asset,field in [('USD','usd_impact'),('GOLD','gold_impact')]:
    adjustments[asset]+=max(-30,min(30,int(event.get(field,0))))
  except (ValueError,TypeError,KeyError):continue
 def pack(groups,weights,asset):
  present={k:v for k,v in groups.items() if v is not None}
  coverage=sum(weights[k] for k in present)
  adj=max(-30,min(30,adjustments[asset]))
  if coverage<60:return {'score':None,'bias':'DADOS INSUFICIENTES','coverage':coverage,'groups':groups,'manual_adjustment':adj}
  base=sum(weights[k]*v for k,v in present.items())/coverage
  total=max(-100,min(100,round(base+adj)))
  return {'score':total,'bias':'ALTISTA' if total>=20 else 'BAIXISTA' if total<=-20 else 'NEUTRO','coverage':coverage,'groups':groups,'manual_adjustment':adj}
 return {'USD':pack(usd,WEIGHTS_USD,'USD'),'GOLD':pack(gold,WEIGHTS_GOLD,'GOLD')}

def audit_detail():
 # Contribution = group score * configured weight / available-weight coverage.
 # It explains the model output; it is not a statistical attribution or causal proof.
 scores=calc()
 result={}
 for asset,weights in [('USD',WEIGHTS_USD),('GOLD',WEIGHTS_GOLD)]:
  data=scores[asset]; coverage=data['coverage']
  groups=[]
  for group,weight in weights.items():
   val=data['groups'].get(group)
   groups.append({'group':group,'weight':weight,'score':val,
    'contribution':round(weight*val/coverage,2) if val is not None and coverage>=60 else None,
    'status':'incluído' if val is not None else 'indisponível'})
  result[asset]={'groups':groups,'manual_adjustment':data['manual_adjustment'],
   'coverage':coverage,'final_score':data['score']}
 return result

def series_diagnostic():
 # These statuses describe data eligibility, not whether a series directly drives a group.
 used={'DGS2','DGS10','DFII5','DFII10','T5YIE','T10YIE','UNRATE','PAYEMS','ICSA','GDPC1','RSAFS'}
 out={}
 for sid,name in SERIES.items():
  obj=state['series'].get(sid)
  eligible=observation(sid) is not None
  if not obj:status='sem dados'
  elif not eligible:
   try:
    age=(datetime.now(timezone.utc).date()-datetime.fromisoformat(obj['latest']['date']).date()).days
    collected=datetime.fromisoformat(obj['fetched_at'])
    status=('observação desatualizada' if age>FRESH_DAYS[sid] else 'coleta desatualizada' if (datetime.now(timezone.utc)-collected).total_seconds()>172800 else 'dados insuficientes ou datas inválidas')
   except (KeyError,ValueError,TypeError):status='dados inválidos'
  elif sid in used:status='elegível e usado no modelo'
  else:status='coletado; não usado no viés'
  try: age_days=(datetime.now(timezone.utc).date()-datetime.fromisoformat(obj['latest']['date']).date()).days if obj else None
  except (KeyError,ValueError,TypeError):age_days=None
  out[sid]={'name':name,'latest':obj.get('latest') if obj else None,
   'previous':obj.get('previous') if obj else None,
   'fetched_at':obj.get('fetched_at') if obj else None,
   'status':status,'fresh_days_limit':FRESH_DAYS.get(sid),
   'age_days':age_days,'cadence':CADENCE.get(sid),'release_time_verified':False,'eligible':eligible}
 return out

GROUP_INPUTS={
 'USD':{
  'Juros/Fed':['DGS2','DGS10'],
  'Inflação':['CPIAUCSL','CPILFESL','PCEPI','PCEPILFE'],
  'Emprego':['PAYEMS','UNRATE','ICSA'],
  'Atividade':['GDPC1','RSAFS'],
  'Condições financeiras':['VIXCLS']},
 'GOLD':{
  'Juros reais':['DFII5','DFII10'],
  'Condições USD':['DGS2','DGS10'],
  'Inflação implícita':['T5YIE','T10YIE'],
  'Risco global':['VIXCLS']}}
GROUP_LIMITATIONS={
 ('USD','Inflação'):'Sem dados de surpresa frente ao consenso ou modelo validado de reação monetária. CPI/PCE são coletados, mas não geram viés direcional automaticamente.',
 ('USD','Condições financeiras'):'VIX isolado não representa condições financeiras dos EUA nem define o sentido do dólar. Necessário índice de condições financeiras validado.',
 ('GOLD','Risco global'):'VIX isolado não determina o sentido do ouro. Necessário modelo validado de aversão a risco e regime de mercado.'}

def group_diagnostic():
 now=datetime.now(timezone.utc)
 result={}
 scores=calc()
 for asset,groups in GROUP_INPUTS.items():
  result[asset]={}
  for name,dependencies in groups.items():
   sources=[]; usable=[]
   for sid in dependencies:
    obj=state.get('series',{}).get(sid,{})
    latest=obj.get('latest') or {}
    eligible=observation(sid,now) is not None
    if eligible:usable.append(sid)
    sources.append({'series_id':sid,'observation_date':latest.get('date'),
      'fetched_at':obj.get('fetched_at'),'usable':eligible,
      'status':series_diagnostic()[sid]['status']})
   value=scores[asset]['groups'].get(name)
   if value is not None:reason='Calculado com cobertura mínima do grupo; veja as variações abaixo.'
   elif name in GROUP_METRICS:reason=f'Cobertura insuficiente no grupo: exigidas {GROUP_MIN[name]} séries com duas observações válidas.'
   elif (asset,name) in GROUP_LIMITATIONS:reason=GROUP_LIMITATIONS[(asset,name)]
   else:reason='Dados elegíveis insuficientes, vencidos ou indisponíveis para o cálculo.'
   result[asset][name]={'score':value,'reason':reason,'sources':sources,
    'metrics':metric_detail(name),'required_series':GROUP_MIN.get(name),'usable_series':usable,'observation_dates':[x['observation_date'] for x in sources if x['usable'] and x['observation_date']]}
 return result

def _history_date(entry):
 try:
  dt=datetime.fromisoformat(entry['timestamp'])
  return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
 except (KeyError,ValueError,TypeError):return datetime.min.replace(tzinfo=timezone.utc)

def meaningful_history():
 # Preserve legacy records on disk, but do not present unchanged monitoring as bias changes.
 result=[]; prior={}
 for item in state.get('history',[]):
  current={a:item.get('scores',{}).get(a,{}).get('score') for a in ('USD','GOLD')}
  if not result or any(current[a]!=prior.get(a) for a in ('USD','GOLD')):
   result.append(item)
  prior=current
 return result

def score_balance(asset,detail):
 groups=detail.get('groups',[])
 positive=sum(max(0,g.get('contribution') or 0) for g in groups)
 negative=sum(abs(min(0,g.get('contribution') or 0)) for g in groups)
 opposing=positive>0 and negative>0
 return {'positive':round(positive,2),'negative':round(negative,2),
  'opposing_forces':opposing,
  'interpretation':('Forças positivas e negativas se contrapõem; a nota líquida pode ocultar divergência.' if opposing else 'Sem contraposição entre contribuições disponíveis.'),
  'note':'Contribuições dos grupos, sem ajuste manual; valores arredondados.'}

def model_validation():
 """Diagnostics only: never modify the original experimental scores."""
 result={}
 for asset,weights in [('USD',WEIGHTS_USD),('GOLD',WEIGHTS_GOLD)]:
  calculated=calc()[asset]
  available={k:v for k,v in calculated['groups'].items() if v is not None}
  metrics={k:metric_detail(k) for k in available}
  positive=sum(weights[k]*max(0,v) for k,v in available.items())
  negative=sum(weights[k]*abs(min(0,v)) for k,v in available.items())
  opposition=round(100*min(positive,negative)/max(positive,negative),1) if max(positive,negative) else 0
  total_metrics=sum(len(rows) for rows in metrics.values())
  eligible_metrics=sum(sum(row['score'] is not None for row in rows) for rows in metrics.values())
  warnings=[]
  if calculated['coverage']<80:warnings.append('Cobertura inferior a 80%; pesos redistribuídos entre grupos disponíveis.')
  if opposition>=50:warnings.append('Forças macroeconômicas opostas relevantes; nota líquida pode ocultar divergência.')
  if calculated['manual_adjustment']:warnings.append('Ajuste manual presente; separar julgamento humano do sinal automático.')
  if any(len([r for r in rows if r['score'] is not None])<len(rows) for rows in metrics.values()):warnings.append('Há séries indisponíveis dentro de grupos calculados.')
  if calculated['score'] is None:warnings.append('Pontuação indisponível por cobertura insuficiente.')
  result[asset]={'score':calculated['score'],'coverage':calculated['coverage'],
   'opposition_pct':opposition,'eligible_metrics':eligible_metrics,'total_metrics':total_metrics,
   'warnings':warnings,'assessment':'EXPERIMENTAL — não validado estatisticamente',
   'methodology':MODEL_VERSION,
   'signal_quality':('SEM DADOS' if calculated['score'] is None else 'COBERTURA LIMITADA' if calculated['coverage']<80 else 'FORÇAS CONTRADITÓRIAS' if opposition>=50 else 'DESCRITIVO — NÃO VALIDADO'),
   'score_excludes':list(k for k,v in calculated['groups'].items() if v is None),
   'note':'Diagnóstico descritivo, não probabilidade de acerto, confiança estatística ou recomendação de operação.',
   'historical_integrity':'Snapshots prospectivos: observações FRED podem sofrer revisão; não há reconstrução por vintages ALFRED.'}
 return result

def snapshot(reason='manual_event',economic_events=None):
 # A snapshot is a recorded live calculation, NOT a reconstructed backtest.
 now=datetime.now(timezone.utc)
 scores=calc()
 entry={'timestamp':now.isoformat(),'session_start':session_start(now).isoformat(),'scores':deepcopy(scores),
        'series_dates':{k:v.get('latest',{}).get('date') for k,v in state.get('series',{}).items()},
        'source':'FRED + manual','model_version':MODEL_VERSION,'reason':reason,
        'inputs':({} if reason=='monitoramento_15min' else {sid:{'latest':v.get('latest'),'previous':v.get('previous'),'fetched_at':v.get('fetched_at')} for sid,v in state.get('series',{}).items()})}
 # First observed score after session start, not necessarily exactly at 04:00.
 session_key=session_start(now).date().isoformat()
 baselines=state.setdefault('session_baselines',{})
 if session_key not in baselines:
  baselines[session_key]={'observed_at':now.isoformat(),'session_start':session_start(now).isoformat(),
   'scores':deepcopy(scores),'note':'primeira observação disponível; não necessariamente às 04:00'}
 if len(baselines)>400:
  for key in sorted(baselines)[:-400]:del baselines[key]
 history=state.setdefault('history',[])
 previous=history[-1].get('scores',{}) if history else {}
 changed={asset:previous.get(asset,{}).get('score')!=scores[asset]['score'] for asset in ('USD','GOLD')}
 model_transition=bool(history and history[-1].get('model_version')!=MODEL_VERSION)
 if not history or any(changed.values()) or model_transition:
  entry['changed_assets']=[asset for asset,flag in changed.items() if flag]
  if model_transition:entry['reason']='model_version_change' # versão muda auditoria, não cria ponto gráfico
  history.append(entry)
  journal('score_change',entry)
 # Histórico independente: uma atualização do ouro não cria ponto no USD e vice-versa.
 per_asset=state.setdefault('change_history',{'USD':[],'GOLD':[]})
 for asset in ('USD','GOLD'):
  points=per_asset.setdefault(asset,[])
  new_score=scores[asset]['score']
  if new_score is not None and (not points or points[-1].get('score')!=new_score):
   points.append({'timestamp':now.isoformat(),'score':new_score,'coverage':scores[asset]['coverage'],
    'reason':reason,'model_version':MODEL_VERSION})
 # A auditoria é independente do gráfico e registra eventos mesmo sem mudança na nota.
 events=state.setdefault('audit_events',[])
 if economic_events:
  for ev in economic_events:
   events.append({'timestamp':now.isoformat(),'type':'economic_observation',
    'series_id':ev['series_id'],'series_name':ev['series_name'],
    'observation_date':ev['observation_date'],'kind':ev['kind'],
    'previous_value':ev.get('previous_value'),'new_value':ev['new_value'],
    'score_before':{a:previous.get(a,{}).get('score') for a in ('USD','GOLD')},
    'score_after':{a:scores[a]['score'] for a in ('USD','GOLD')},
    'score_delta':{a:(scores[a]['score']-previous[a]['score']) if isinstance(scores[a]['score'],(int,float)) and isinstance(previous.get(a,{}).get('score'),(int,float)) else None for a in ('USD','GOLD')},
    'note':'Variação total da consulta; não atribuição causal individual à série'})
 for asset in ('USD','GOLD'):
  before=previous.get(asset,{})
  if before and (before.get('coverage')!=scores[asset]['coverage'] or before.get('groups')!=scores[asset]['groups']):
   events.append({'timestamp':now.isoformat(),'type':'model_recalculation','asset':asset,
    'previous_score':before.get('score'),'new_score':scores[asset]['score'],
    'previous_coverage':before.get('coverage'),'new_coverage':scores[asset]['coverage'],
    'changed_groups':[{'name':name,'previous':before.get('groups',{}).get(name),
     'current':value} for name,value in scores[asset]['groups'].items()
     if before.get('groups',{}).get(name)!=value],
    'note':'Recalculo do modelo; pode incluir dados novos, revisões, perda de elegibilidade ou eventos manuais'})
 # No silent deletion of audit and scoring history.
 save()
 return scores

class Handler(BaseHTTPRequestHandler):
 def respond(self,code,obj):
  data=json.dumps(obj,ensure_ascii=False).encode('utf-8');self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if self.path=='/':
   data=(ROOT/'index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
  if self.path=='/api/health':
   try:
    with database() as conn:
     integrity=conn.execute('PRAGMA quick_check').fetchone()[0]
     stored=conn.execute('SELECT COUNT(*) FROM state').fetchone()[0]
    with lock:
     result={'version':MODEL_VERSION,'database_integrity':integrity,'state_rows':stored,'refresh_in_progress':bool(state.get('refresh_in_progress')),'last_success':state.get('last_success'),'last_result':state.get('last_result'),'series_count':len(state.get('series',{}))}
    self.respond(200 if integrity=='ok' else 503,result)
   except (sqlite3.Error,OSError) as exc:
    self.respond(503,{'version':MODEL_VERSION,'database_integrity':'error','detail':type(exc).__name__})
   return
  if self.path=='/api/status':
   with lock:self.respond(200,{'data':{**state,'history':meaningful_history()[-30:]},'scores':calc(),'catalog':SERIES,'configured':bool(get_key()),'model_version':MODEL_VERSION,'validation':model_validation(),'audit_detail':audit_detail(),'balance':{a:score_balance(a,audit_detail()[a]) for a in ('USD','GOLD')},'group_diagnostic':group_diagnostic(),'diagnostic':series_diagnostic(),'session_baselines':state.get('session_baselines',{}),'session_start':session_start().isoformat()});return
  if self.path=='/api/audit':
   with lock:
    result={'version':MODEL_VERSION,'time_utc':datetime.now(timezone.utc).isoformat(),
      'scores':calc(),'validation':model_validation(),'detail':audit_detail(),'group_diagnostic':group_diagnostic(),'series':series_diagnostic(),'auto_events':state.get('auto_events',[])[-50:],
      'history_count':len(state.get('history',[])),'audit_events':state.get('audit_events',[])[-100:]}
    for sid,name in SERIES.items():
     obj=state['series'].get(sid,{})
     result['series'][sid]={'name':name,'latest':obj.get('latest'),'previous':obj.get('previous'),
       'fetched_at':obj.get('fetched_at'),'usable':observation(sid) is not None,
       'fresh_days_limit':FRESH_DAYS.get(sid)}
    self.respond(200,result)
   return
  if self.path=='/api/calibration':
   report_path=DATA_DIR/'calibracao_atlas.json'
   if not report_path.exists():
    self.respond(200,{'available':False,'message':'Execute calibrate_signals.py após gerar validacao_atlas.json.'});return
   try:
    if report_path.stat().st_size>5_000_000:raise ValueError('Relatório excede 5 MB')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if not isinstance(report,dict) or not isinstance(report.get('groups'),list):raise ValueError('Formato inválido')
    self.respond(200,{'available':True,'data':{**report,'groups':report['groups'][:20]}})
   except (ValueError,OSError,json.JSONDecodeError) as exc:self.respond(200,{'available':False,'message':'Relatório inválido: '+str(exc)})
   return
  if self.path=='/api/backtest':
   report_path=DATA_DIR/'validacao_atlas.json'
   if not report_path.exists():
    self.respond(200,{'available':False,'message':'Execute validate_history.py com --out validacao_atlas para gerar o relatório.'});return
   try:
    if report_path.stat().st_size>10_000_000:raise ValueError('Relatório excede 10 MB')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if not isinstance(report,dict) or not isinstance(report.get('summary'),list):raise ValueError('Formato inválido')
    self.respond(200,{'available':True,'generated_at_utc':datetime.fromtimestamp(report_path.stat().st_mtime,timezone.utc).isoformat(),
                      'summary':report['summary'][:100], 'segments':report.get('segments',[])[:100], 'nonoverlapping_summary':report.get('nonoverlapping_summary',[])[:100], 'signal_count':report.get('signal_count',0),
                      'sample_count':len(report.get('samples',[])), 'skipped':report.get('skipped',{}),
                      'limitations':report.get('limitations',[])})
   except (ValueError,OSError,json.JSONDecodeError) as exc:self.respond(200,{'available':False,'message':'Relatório inválido: '+str(exc)})
   return
  if self.path=='/api/history':
   with lock:
    per_asset=state.get('change_history',{})
    # Migração compatível: reconstrói apenas registros já existentes, sem criar dados retroativos.
    if not any(per_asset.get(asset) for asset in ('USD','GOLD')):
     per_asset={'USD':[],'GOLD':[]}
     previous={}
     for h in state.get('history',[]):
      for asset in ('USD','GOLD'):
       val=h.get('scores',{}).get(asset,{}).get('score')
       if asset not in previous or previous[asset]!=val:
        per_asset[asset].append({'timestamp':h.get('timestamp'),'score':val,'reason':h.get('reason')})
       previous[asset]=val
    self.respond(200,{'per_asset':{asset:per_asset.get(asset,[]) for asset in ('USD','GOLD')}})
   return
  self.respond(404,{'error':'Não encontrado'})
 def do_POST(self):
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length>15000:raise ValueError('Requisição grande demais')
   body=json.loads(self.rfile.read(length)) if length else {}
   if self.path=='/api/refresh':
    threading.Thread(target=refresh,daemon=True).start();self.respond(202,{'message':'Consulta iniciada'});return
   if self.path=='/api/events':
    title=str(body.get('title','')).strip()[:120]
    if not title:raise ValueError('Título obrigatório')
    usd=int(body.get('usd_impact',0));gold=int(body.get('gold_impact',0))
    if not(-30<=usd<=30 and -30<=gold<=30):raise ValueError('Impactos entre -30 e +30')
    event={'title':title,'usd_impact':usd,'gold_impact':gold,'notes':str(body.get('notes',''))[:500],'created_at':datetime.now(timezone.utc).isoformat(),'event_id':str(time.time_ns())}
    with lock:state['events'].append(event);snapshot()
    self.respond(201,event);return
   self.respond(404,{'error':'Não encontrado'})
  except Exception as exc:self.respond(400,{'error':str(exc)})
 def log_message(self,format,*args):pass
if __name__=='__main__':
 port=int(os.environ.get('PORT','8765'))
 print(f'Atlas USD & Gold Macro: porta {port}',flush=True)
 threading.Thread(target=worker,daemon=True).start()
 ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
