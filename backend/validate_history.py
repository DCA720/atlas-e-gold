"""Validação prospectiva de sinais registrados, com preços externos em CSV.

Uso: python validate_history.py --prices precos.csv --out relatorio
CSV: timestamp,USD,GOLD (UTC ISO-8601; preço USD = DXY ou outro proxy declarado;
GOLD = XAUUSD). Também aceita colunas dxy e xauusd.

Não usa datas de observação FRED para reconstruir sinais. Usa apenas timestamps
em que o Atlas registrou o score, e preços posteriores ao registro.
"""
import argparse
import csv
import json
import sqlite3
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from math import sqrt

ROOT=Path(__file__).resolve().parent

def parse_time(value):
    dt=datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Datas precisam ter fuso horário explícito (ex.: +00:00 ou Z).')
    return dt.astimezone(timezone.utc)

def load_signals(db_path):
    with sqlite3.connect(db_path) as conn:
        row=conn.execute('SELECT payload FROM state WHERE id=1').fetchone()
    if not row:raise ValueError('Banco sem estado do Atlas')
    state=json.loads(row[0]); output=[]
    for asset in ('USD','GOLD'):
        for item in state.get('change_history',{}).get(asset,[]):
            value=item.get('score')
            if not isinstance(value,(int,float)) or isinstance(value,bool):continue
            output.append({'asset':asset,'timestamp':parse_time(item['timestamp']),
                           'score':value,'model_version':item.get('model_version','não registrada'),
                           'reason':item.get('reason','não registrado')})
    return sorted(output,key=lambda x:(x['asset'],x['timestamp']))

def load_prices(csv_path):
    data={'USD':[],'GOLD':[]}
    with open(csv_path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames:raise ValueError('CSV vazio')
        columns={name.strip().lower():name for name in reader.fieldnames}
        if 'timestamp' not in columns:raise ValueError('CSV precisa da coluna timestamp')
        names={'USD':next((columns[k] for k in ('usd','dxy') if k in columns),None),
               'GOLD':next((columns[k] for k in ('gold','xauusd') if k in columns),None)}
        if not any(names.values()):raise ValueError('CSV precisa de USD/DXY e/ou GOLD/XAUUSD')
        for row in reader:
            dt=parse_time(row[columns['timestamp']])
            for asset,col in names.items():
                if not col or not row.get(col):continue
                try:price=float(row[col])
                except ValueError:continue
                if 0<price<float('inf'):data[asset].append((dt,price))
    for asset in data:
        data[asset].sort()
        if len({t for t,_ in data[asset]})!=len(data[asset]):
            raise ValueError(f'Timestamps duplicados para {asset}')
    return data

def wilson_interval(successes, n, z=1.96):
    """Intervalo de Wilson descritivo; pressupõe amostras independentes."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    margin = z * sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return [round(100*(center-margin), 2), round(100*(center+margin), 2)]


def summarize(samples, asset, hours, label):
    n = len(samples)
    if not n:
        return None
    hits = sum(r['directional_hit'] for r in samples)
    returns = [r['directional_return_pct'] for r in samples]
    up = sum(r['direction'] == 1 for r in samples)
    # Comparador ingênuo: sempre prever alta, na mesma amostra e janela.
    baseline_hits = sum(r['return_pct'] > 0 for r in samples)
    return {'asset':asset, 'horizon_hours':hours, 'segment':label, 'n':n,
            'hit_rate_pct':round(100*hits/n, 2),
            'wilson_95_pct':wilson_interval(hits,n),
            'avg_directional_return_pct':round(mean(returns),5),
            'median_directional_return_pct':round(median(returns),5),
            'baseline_always_up_hit_pct':round(100*baseline_hits/n,2),
            'excess_hit_vs_always_up_pp':round(100*(hits-baseline_hits)/n,2),
            'bullish_signals':up,'bearish_signals':n-up,
            'sample_warning':n<30,
            'note':'Descritivo: intervalo de Wilson não ajustado para dependência temporal; não é significância estatística.'}


def nonoverlapping(samples):
    """Seleciona janelas cronológicas sem sobreposição, separadamente por ativo/horizonte."""
    output=[]; last_end=None
    for r in sorted(samples,key=lambda x:x['entry_time_utc']):
        entry=parse_time(r['entry_time_utc']); end=parse_time(r['exit_time_utc'])
        if last_end is None or entry >= last_end:
            output.append(r);last_end=end
    return output

def evaluate(signals,prices,horizons=(1,4,24),max_delay_minutes=60,threshold=20):
    """Usa primeiro preço >= instante do sinal e primeiro preço >= horizonte.
    Descarta amostras se o primeiro preço disponível estiver longe demais.
    """
    rows=[]; skipped={}
    for signal in signals:
        asset=signal['asset']; observations=prices.get(asset,[])
        score=signal['score']
        if abs(score)<threshold:continue
        direction=1 if score>=threshold else -1
        times=[x[0] for x in observations]
        for hours in horizons:
            key=f'{asset}_{hours}h'
            start_idx=bisect_left(times,signal['timestamp'])
            target=signal['timestamp']+timedelta(hours=hours)
            end_idx=bisect_left(times,target)
            if start_idx>=len(times) or end_idx>=len(times):
                skipped[key]=skipped.get(key,0)+1;continue
            start_t,p0=observations[start_idx];end_t,p1=observations[end_idx]
            if (start_t-signal['timestamp']).total_seconds()>max_delay_minutes*60 or (end_t-target).total_seconds()>max_delay_minutes*60:
                skipped[key]=skipped.get(key,0)+1;continue
            change_pct=(p1/p0-1)*100
            rows.append({'asset':asset,'signal_time_utc':signal['timestamp'].isoformat(),
                         'model_version':signal['model_version'],'score':score,'direction':direction,
                         'horizon_hours':hours,'entry_time_utc':start_t.isoformat(),
                         'exit_time_utc':end_t.isoformat(),'entry_price':p0,'exit_price':p1,
                         'return_pct':round(change_pct,6),'directional_hit':int(direction*change_pct>0),
                         'directional_return_pct':round(direction*change_pct,6)})
    groups={}
    for r in rows:groups.setdefault((r['asset'],r['horizon_hours']),[]).append(r)
    summary=[];segments=[];nonoverlap_summary=[]
    for (asset,hours),samples in sorted(groups.items()):
        summary.append(summarize(samples,asset,hours,'todos'))
        nonoverlap_summary.append(summarize(nonoverlapping(samples),asset,hours,'sem_sobreposicao'))
        for label,predicate in [('moderado_20_39',lambda x:20<=abs(x['score'])<40),
                                ('forte_40_69',lambda x:40<=abs(x['score'])<70),
                                ('extremo_70_100',lambda x:abs(x['score'])>=70)]:
            subset=[r for r in samples if predicate(r)]
            if subset:segments.append(summarize(subset,asset,hours,label))
    return {'summary':summary,'segments':segments,
            'nonoverlapping_summary':[x for x in nonoverlap_summary if x],
            'samples':rows,'skipped':skipped,'signal_count':len(signals),
            'limitations':['Não é backtest de sinais anteriores à instalação do Atlas.',
                           'Preço de entrada é a primeira cotação disponível após o sinal, nunca anterior.',
                           'Não considera spread, slippage, comissões ou execução real.',
                           'Sinais consecutivos e horizontes sobrepostos não são independentes.',
                           'Intervalo de Wilson é apenas descritivo; não corrige dependência nem prova capacidade preditiva.',
                           'Comparador sempre alta é ingênuo; diferenças não estabelecem significância estatística.',
                           'Amostras pequenas (menos de 30) são sinalizadas; não equivalem a validação fora da amostra.',
                           'É necessário declarar a origem, o fuso e a natureza do proxy USD (ex.: DXY).']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default=str(ROOT/'atlas.db'))
    p.add_argument('--prices',required=True,help='CSV com timestamp,USD,GOLD')
    p.add_argument('--out',default='validacao_atlas')
    p.add_argument('--horizons',default='1,4,24',help='Horizontes em horas, separados por vírgula')
    p.add_argument('--max-delay-minutes',type=int,default=60)
    args=p.parse_args()
    horizons=tuple(int(x) for x in args.horizons.split(','))
    if not horizons or any(x<=0 for x in horizons) or args.max_delay_minutes<0:p.error('Horizontes positivos e atraso não negativo são obrigatórios')
    report=evaluate(load_signals(args.db),load_prices(args.prices),horizons,args.max_delay_minutes)
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    (out.with_suffix('.json')).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    with out.with_suffix('.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['asset','signal_time_utc','model_version','score','direction','horizon_hours','entry_time_utc','exit_time_utc','entry_price','exit_price','return_pct','directional_hit','directional_return_pct'])
        writer.writeheader();writer.writerows(report['samples'])
    print(f"Sinais: {report['signal_count']} | amostras válidas: {len(report['samples'])}")
    for line in report['summary']:print(f"{line['asset']} {line['horizon_hours']}h: {line['n']} amostras, {line['hit_rate_pct']}% acertos")
    print(f'Relatórios: {out.with_suffix(".json")} e {out.with_suffix(".csv")}')

if __name__=='__main__':main()
