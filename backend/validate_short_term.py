"""Validação prospectiva das leituras de curto prazo do Atlas.

Não reconstrói sinais a partir do FRED atual: exige snapshots históricos registrados
na ocasião e preços externos com carimbo de data/hora verificável.

Uso: python validate_short_term.py --signals sinais.csv --prices precos.csv --out resultado.json
Sinais: signal_time_utc,asset,horizon,score (asset USD/GOLD, horizon 1d/5d)
Preços: time_utc,asset,close (preço positivo; USD requer proxy USD definido pelo usuário)
"""
import argparse,csv,json
from datetime import datetime,timezone
from pathlib import Path
from statistics import mean

def dt(x):
 d=datetime.fromisoformat(x.replace('Z','+00:00'))
 if d.tzinfo is None or d.utcoffset() is None:raise ValueError('Horário sem fuso UTC: '+x)
 return d.astimezone(timezone.utc)

def read_csv(path):
 with open(path,newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))

def validate(signals,prices):
 px={}
 for r in prices:
  t=dt(r['time_utc']);v=float(r['close'])
  if v<=0:raise ValueError('Preço inválido')
  px.setdefault(r['asset'],[]).append((t,v))
 for rows in px.values():rows.sort()
 groups={}
 for r in signals:
  t=dt(r['signal_time_utc']);a=r['asset'];h=r['horizon'];s=float(r['score'])
  if h not in ('1d','5d') or a not in ('USD','GOLD') or abs(s)>100:raise ValueError('Sinal inválido')
  if not s:continue
  observations=px.get(a,[])
  # Preço de entrada no primeiro fechamento ESTRITAMENTE posterior ao sinal.
  # Resultado no fechamento da N-ésima sessão posterior à entrada.
  future=[(tp,p) for tp,p in observations if tp>t]
  steps=1 if h=='1d' else 5
  if len(future)<=steps:continue
  start,p0=future[0];end,p1=future[steps]
  direction=1 if s>0 else -1
  ret=direction*(p1/p0-1)*100
  groups.setdefault((a,h),[]).append({'signal_time':t,'entry_time':start,'exit_time':end,'directional_return_pct':ret,'hit':ret>0})
 results={}
 for (a,h),rows in groups.items():
  rows.sort(key=lambda x:x['signal_time'])
  # Não contar operações sobrepostas como amostras independentes.
  selected=[];last_exit=None
  for r in rows:
   if last_exit is None or r['entry_time']>last_exit:
    selected.append(r);last_exit=r['exit_time']
  cut=int(len(selected)*.7)
  def stats(rs):return {'n':len(rs),'hit_rate_pct':round(100*sum(r['hit'] for r in rs)/len(rs),2) if rs else None,'mean_directional_return_pct':round(mean(r['directional_return_pct'] for r in rs),5) if rs else None}
  results[f'{a}_{h}']={'total_eligible':len(rows),'non_overlapping':len(selected),'train':stats(selected[:cut]),'test':stats(selected[cut:]),'test_sufficient':len(selected[cut:])>=30}
 return {'status':'experimental','results':results,'limitations':['Preços devem ser de fonte externa verificável, com horário correto e sem revisão retrospectiva dos sinais.','USD precisa de um proxy explicitamente definido (ex.: índice DXY); não misturar pares e índices.','Entradas e saídas usam fechamentos posteriores ao sinal; não incluem spread, slippage ou custos.','Amostras com sobreposição são excluídas; mínimo de 30 observações fora da amostra é somente triagem, não comprova eficácia.','Não é possível validar historicamente a RC5 sem snapshots históricos reais das pontuações de curto prazo.']}

def main():
 p=argparse.ArgumentParser();p.add_argument('--signals',required=True);p.add_argument('--prices',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 result=validate(read_csv(a.signals),read_csv(a.prices));Path(a.out).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
