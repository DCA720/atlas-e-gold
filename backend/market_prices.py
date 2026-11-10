"""Coleta opcional de preços horários para validação PROSPECTIVA.

Fonte experimental: endpoint NÃO OFICIAL do Yahoo Finance. DX-Y.NYB é
índice dólar quando disponível; GC=F é futuro de ouro, NÃO spot XAU/USD.
Falhas nunca geram preços sintéticos nem substituem preços já gravados.
"""
import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DATA_DIR=Path(os.environ.get('ATLAS_DATA_DIR',str(ROOT))).resolve()
FIELDS=['timestamp','USD','GOLD']
DEFAULT_SYMBOLS={'USD':'DX-Y.NYB','GOLD':'GC=F'}

def parse_chart(payload, now=None):
    now=now or datetime.now(timezone.utc)
    chart=payload.get('chart',{})
    if chart.get('error'):raise ValueError(f"Erro do provedor: {chart['error']}")
    results=chart.get('result') or []
    if len(results)!=1:raise ValueError('Resposta sem série única')
    result=results[0]; timestamps=result.get('timestamp') or []
    quotes=(result.get('indicators',{}).get('quote') or [{}])[0]
    closes=quotes.get('close') or []
    if len(timestamps)!=len(closes):raise ValueError('Timestamps e fechamentos inconsistentes')
    interval=result.get('meta',{}).get('dataGranularity','')
    if interval and interval not in ('1h','60m'):raise ValueError('Granularidade inesperada')
    rows={}
    for ts,close in zip(timestamps,closes):
        if not isinstance(ts,(int,float)) or isinstance(ts,bool):continue
        if not isinstance(close,(int,float)) or isinstance(close,bool) or not math.isfinite(close) or close<=0:continue
        dt=datetime.fromtimestamp(ts,timezone.utc)
        # O timestamp do candle indica sua ABERTURA. Não usar candles ainda abertos.
        if ts+3600>now.timestamp():continue
        rows[dt.isoformat()]=float(close)
    return rows

def fetch_prices(symbol, timeout=15, opener=None):
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(symbol,safe='')+'?interval=1h&range=60d'
    req=urllib.request.Request(url,headers={'User-Agent':'AtlasMacroValidation/2.7','Accept':'application/json'})
    if opener is None:opener=urllib.request.urlopen
    with opener(req,timeout=timeout) as response:
        payload=json.load(response)
    return parse_chart(payload)

def merge_csv(path, fetched):
    existing={}
    if path.exists():
        with path.open(newline='',encoding='utf-8-sig') as file:
            reader=csv.DictReader(file)
            if reader.fieldnames!=FIELDS:raise ValueError('CSV existente com colunas inesperadas; não sobrescrever')
            for row in reader:
                ts=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
                if ts.tzinfo is None:raise ValueError('Timestamp sem fuso')
                key=ts.astimezone(timezone.utc).isoformat()
                if key in existing:raise ValueError('CSV com timestamp duplicado')
                existing[key]={'timestamp':key,'USD':row['USD'],'GOLD':row['GOLD']}
    added=0
    for asset,points in fetched.items():
        for ts,price in points.items():
            row=existing.setdefault(ts,{'timestamp':ts,'USD':'','GOLD':''})
            if not row[asset]:row[asset]=str(price);added+=1
    if not added:return 0
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    try:
        with temp.open('w',newline='',encoding='utf-8') as file:
            writer=csv.DictWriter(file,fieldnames=FIELDS);writer.writeheader()
            writer.writerows(existing[key] for key in sorted(existing))
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()
    return added

def cycle(args):
    fetched={}; errors={}
    for asset,symbol in DEFAULT_SYMBOLS.items():
        symbol=getattr(args,asset.lower()+'_symbol')
        try:fetched[asset]=fetch_prices(symbol)
        except (OSError,ValueError,KeyError,TypeError,TimeoutError) as exc:errors[asset]=str(exc)
    if not fetched:
        print('Nenhuma fonte respondeu; relatório anterior preservado.',file=sys.stderr)
        return False
    added=merge_csv(Path(args.prices),fetched)
    print(f'Novos fechamentos gravados: {added}; fontes disponíveis: {list(fetched)}')
    if errors:print('Falhas de coleta (sem preencher dados artificialmente): '+str(errors),file=sys.stderr)
    # Importar sob demanda; manter mesmo motor da versão 2.6.
    from validate_history import evaluate,load_prices,load_signals
    db=Path(args.db)
    if not db.exists():
        print('Banco não encontrado; CSV preservado, validação adiada.',file=sys.stderr)
        return False
    report=evaluate(load_signals(db),load_prices(args.prices))
    report['market_data']={'provider':'Yahoo Finance chart (não oficial)',
      'symbols':{'USD':args.usd_symbol,'GOLD':args.gold_symbol},
      'instrument_notes':{'USD':'Índice dólar (DXY) se o símbolo estiver disponível',
                          'GOLD':'GC=F: futuro de ouro, NÃO XAU/USD spot'},
      'granularity':'1h; candles fechados','source_errors':errors,
      'generated_at_utc':datetime.now(timezone.utc).isoformat(),
      'warning':'Dados horários e símbolos são proxies; não é validação de XAU/USD spot.'}
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_suffix('.json.tmp')
    try:
        temp.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        os.replace(temp,out.with_suffix('.json'))
    finally:
        if temp.exists():temp.unlink()
    print(f"Relatório atualizado: {out.with_suffix('.json')} | amostras: {len(report['samples'])}")
    return True

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prices',default=str(DATA_DIR/'precos_mercado.csv'))
    p.add_argument('--db',default=str(DATA_DIR/'atlas.db'))
    p.add_argument('--out',default=str(DATA_DIR/'validacao_atlas'))
    p.add_argument('--usd-symbol',default=DEFAULT_SYMBOLS['USD'])
    p.add_argument('--gold-symbol',default=DEFAULT_SYMBOLS['GOLD'])
    p.add_argument('--interval-minutes',type=int,default=60)
    p.add_argument('--loop',action='store_true',help='Repetir a coleta a cada intervalo (deixe terminal aberto)')
    args=p.parse_args()
    if args.interval_minutes<15:p.error('Intervalo mínimo: 15 minutos')
    while True:
        try:cycle(args)
        except Exception as exc:print(f'Falha na validação, sem apagar dados anteriores: {exc}',file=sys.stderr)
        if not args.loop:break
        time.sleep(args.interval_minutes*60)

if __name__=='__main__':main()
