"""Atlas EUR RC5.2: auditoria de metadados e comparabilidade, somente leitura.

Não habilita score nem sinais. Reutiliza RC5.1 e consulta metadados JSON-stat
Eurostat de desemprego e PIB; falha fechada se fonte ou filtros divergirem.
"""
import contextlib
import io
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone


VERSION = 'eur-rc5.2-methodology-audit-0.5.2'
BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
SPECS = {
    'unemployment': {
        'dataset': 'une_rt_m',
        'filters': {'geo': 'EA21', 's_adj': 'SA', 'age': 'TOTAL', 'sex': 'T', 'unit': 'PC_ACT'},
        'expected': {'s_adj': 'SA', 'unit': 'PC_ACT', 'age': 'TOTAL', 'sex': 'T'},
        'us_series': 'UNRATE',
        'methodology_note': 'Ambas taxas dessazonalizadas, mas harmonização ILO, cobertura populacional e revisões ainda exigem validação.'
    },
    'activity': {
        'dataset': 'namq_10_gdp',
        'filters': {'geo': 'EA21', 'na_item': 'B1G', 's_adj': 'SCA', 'unit': 'CLV_PCH_PRE'},
        'expected': {'na_item': 'B1G', 's_adj': 'SCA', 'unit': 'CLV_PCH_PRE'},
        'us_series': 'GDPC1',
        'methodology_note': 'CLV_PCH_PRE = crescimento trimestral do PIB real Eurostat; GDPC1 convertido de nível para taxa não anualizada. Conferir vintages e cobertura geográfica.'
    },
}


def eurostat_metadata(dataset, filters, timeout=25):
    params = {**filters, 'sinceTimePeriod': '2026-01', 'lang': 'EN'}
    url = BASE + dataset + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'Atlas-EUR-RC52/0.5.2', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(3_000_001)
    if len(raw) > 3_000_000:
        raise ValueError('Resposta Eurostat maior que 3MB')
    data = json.loads(raw)
    ids, sizes = data['id'], data['size']
    if len(ids) != len(sizes):
        raise ValueError('Dimensoes invalidas')
    dims = {}
    for dim, size in zip(ids, sizes):
        index = data['dimension'][dim]['category']['index']
        codes = list(index) if isinstance(index, dict) else list(index)
        dims[dim] = {'size': size, 'codes': codes[:12]}
    return {'dataset': dataset, 'requested_filters': filters, 'dimensions': dims,
            'observation_cells': len(data.get('value', {})),
            'source': 'Eurostat JSON-stat 1.0', 'retrieved_at_utc': datetime.now(timezone.utc).isoformat()}


def check_metadata(meta, expected):
    dims = meta['dimensions']
    reasons = []
    for key, code in expected.items():
        d = dims.get(key)
        if not d or d['size'] != 1 or d['codes'] != [code]:
            reasons.append(f'{key}: esperado somente {code}, recebido {d}')
    geo = dims.get('geo')
    if not geo or geo['size'] != 1 or geo['codes'] != ['EA21']:
        reasons.append('Geografia EA21 nao confirmada')
    if not meta['observation_cells']:
        reasons.append('Sem observacoes numericas')
    return {'source_filters_verified': not reasons, 'issues': reasons}


def evaluate(rc51, metadata_fetch=eurostat_metadata):
    aligned = rc51['aligned_descriptive']
    results = {}
    for name, spec in SPECS.items():
        entry = {'european_dataset': spec['dataset'], 'us_series': spec['us_series'],
                 'methodology_note': spec['methodology_note'], 'score_eligible': False}
        try:
            meta = metadata_fetch(spec['dataset'], spec['filters'])
            entry['metadata'] = meta
            entry.update(check_metadata(meta, spec['expected']))
        except Exception as exc:
            entry.update({'source_filters_verified': False, 'issues': [f'Falha consulta: {type(exc).__name__}: {str(exc)[:120]}']})
        if name == 'activity':
            us = aligned.get('activity', {}).get('us_same_quarter', {})
            entry['period_aligned'] = (us.get('status') == 'descritivo' and us.get('quarter') == aligned['activity'].get('eur_quarter'))
            entry['descriptive_difference_pp'] = (round(aligned['activity']['eur_reported_pct'] - us['qoq_pct_nonannualized'], 3)
                if entry['period_aligned'] and isinstance(aligned['activity'].get('eur_reported_pct'), (int, float)) else None)
        else:
            u = aligned.get('unemployment', {})
            entry['period_aligned'] = u.get('status') == 'descritivo'
            entry['descriptive_difference_pp'] = u.get('difference_pp') if entry['period_aligned'] else None
        entry['methodology_fully_verified'] = False
        results[name] = entry
    return {
        'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(), 'asset': 'EUR/USD',
        'source_model_version': rc51.get('model_version'),
        'methodology_audit': results,
        'inflation': {'status': 'bloqueado', 'reason': 'HICP Europa e CPI EUA nao harmonizados; outubro/2025 ausente na FRED'},
        'rates': {'status': 'bloqueado', 'reason': 'BCE deposito e teto Fed nao equivalentes'},
        'eligible_factors': {'inflation': False, 'unemployment': False, 'rates': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'status': 'Auditoria de metadados: comparacoes descritivas, sem elegibilidade automatica',
        'limitations': ['Metadados e datas alinhados nao comprovam equivalencia estatistica.',
                        'Resultados dependem da geografia EA21 e das revisoes das fontes.',
                        'Sem calendario de divulgacao, expectativas ou vintages nao ha surpresa macro nem sinal.']
    }


def main():
    from atlas_eur_rc51 import main as rc51_main
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc51_main()
    rc51 = json.loads(output.getvalue())
    print(json.dumps(evaluate(rc51), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
