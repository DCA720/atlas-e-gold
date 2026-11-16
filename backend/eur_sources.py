"""Atlas EUR - coleta experimental isolada de câmbio de referência do BCE.

Não gera score, não altera USD/GOLD e não grava no PostgreSQL.
Fonte: BCE EXR, taxa de referência EUR/USD (USD por EUR), frequência diária.
"""
import csv
import io
import json
import urllib.request
from datetime import datetime, timezone

ECB_URL = ('https://data-api.ecb.europa.eu/service/data/EXR/'
           'D.USD.EUR.SP00.A?format=csvdata&lastNObservations=40')


def collect_eurusd(timeout=20):
    request = urllib.request.Request(ECB_URL, headers={'User-Agent': 'AtlasMacro-EUR/0.1', 'Accept': 'text/csv'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(1_500_001)
    if len(content) > 1_500_000:
        raise ValueError('Resposta do BCE excede o limite de 1,5 MB')
    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    if not reader.fieldnames or not {'TIME_PERIOD', 'OBS_VALUE'}.issubset(reader.fieldnames):
        raise ValueError('Formato CSV inesperado do BCE')
    observations = {}
    for row in reader:
        try:
            date = datetime.strptime(row['TIME_PERIOD'], '%Y-%m-%d').date()
            price = float(row['OBS_VALUE'])
            if price > 0 and price < 100 and date <= datetime.now(timezone.utc).date():
                observations[date.isoformat()] = price
        except (ValueError, TypeError, KeyError):
            continue
    recent = [{'date': date, 'value': observations[date]} for date in sorted(observations, reverse=True)]
    if len(recent) < 2:
        raise ValueError('Histórico EUR/USD insuficiente')
    return {'asset': 'EUR', 'pair': 'EUR/USD', 'source': 'ECB EXR reference rate',
            'unit': 'USD por 1 EUR', 'frequency': 'daily',
            'collected_at_utc': datetime.now(timezone.utc).isoformat(),
            'latest': recent[0], 'previous': recent[1], 'recent': recent,
            'score': None, 'status': 'coleta de referência; sem viés macro calculado',
            'note': 'Cotação de referência diária, não feed intradiário nem preço de execução.'}


if __name__ == '__main__':
    print(json.dumps(collect_eurusd(), ensure_ascii=False, indent=2))
