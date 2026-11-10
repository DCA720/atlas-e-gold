"""Atlas 2.9.1: diagnóstico de limiares SEM recalibrar o modelo automaticamente.

Entrada: validacao_atlas.json produzido por validate_history.py.
Saída: calibracao_atlas.json. Compara limiares fixos em divisão cronológica.
Não interpreta amostras correlacionadas como independentes.
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent
CANDIDATES = (20, 30, 40, 50, 60)

def _time(row):
    return datetime.fromisoformat(row['signal_time_utc'].replace('Z', '+00:00'))

def _stats(rows):
    if not rows:
        return {'n': 0, 'hit_rate_pct': None, 'mean_directional_return_pct': None,
                'median_directional_return_pct': None, 'always_up_hit_pct': None}
    n = len(rows)
    return {'n': n,
            'hit_rate_pct': round(100 * sum(int(x['directional_hit']) for x in rows) / n, 2),
            'mean_directional_return_pct': round(mean(float(x['directional_return_pct']) for x in rows), 5),
            'median_directional_return_pct': round(median(float(x['directional_return_pct']) for x in rows), 5),
            'always_up_hit_pct': round(100 * sum(float(x['return_pct']) > 0 for x in rows) / n, 2)}

def calibrate(report, train_fraction=0.7, min_train=30, min_test=20):
    if not 0 < train_fraction < 1:
        raise ValueError('A divisão treino/teste deve estar entre 0 e 1')
    groups = defaultdict(list)
    for row in report.get('samples', []):
        if row.get('asset') not in ('USD', 'GOLD'):
            continue
        if not isinstance(row.get('score'), (int, float)) or isinstance(row.get('score'), bool):
            continue
        groups[(row['asset'], int(row['horizon_hours']))].append(row)
    results = []
    for (asset, horizon), rows in sorted(groups.items()):
        # Evita que o mesmo timestamp apareça nos dois lados da divisão.
        times = sorted({_time(r) for r in rows})
        cut = max(1, min(len(times)-1, int(len(times)*train_fraction))) if len(times)>1 else 0
        split = times[cut] if cut else None
        train = [r for r in rows if split and _time(r)<split]
        test = [r for r in rows if split and _time(r)>=split]
        options = []
        for threshold in CANDIDATES:
            a = [r for r in train if abs(r['score']) >= threshold]
            b = [r for r in test if abs(r['score']) >= threshold]
            options.append({'threshold': threshold, 'train': _stats(a), 'test': _stats(b),
                            'enough_samples': len(a)>=min_train and len(b)>=min_test})
        results.append({'asset': asset, 'horizon_hours': horizon,
                        'split_utc': split.isoformat() if split else None,
                        'train_total': len(train), 'test_total': len(test),
                        'options': options,
                        'assessment': 'Amostras insuficientes para avaliar limiares' if not any(o['enough_samples'] for o in options)
                                      else 'Comparação descritiva; sem escolha automática de limiar'})
    return {'version': '2.9.1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'default_threshold': 20, 'threshold_changed': False,
            'train_fraction': train_fraction, 'min_train': min_train, 'min_test': min_test,
            'groups': results,
            'limitations': [
                'Divisão cronológica descritiva, não constitui validação walk-forward independente.',
                'Os mesmos sinais e preços podem gerar janelas sobrepostas; resultados não são independentes.',
                'Amostras e dados devem ser prospectivos, com timestamps reais e preços posteriores ao sinal.',
                'Sem taxas, slippage ou execução; proxies DXY e futuro de ouro podem divergir dos ativos negociados.',
                'Não escolher o melhor limiar no teste: isso contamina a avaliação fora da amostra.',
                'Nenhum limiar é alterado automaticamente. O padrão permanece ±20.',
                'Um conjunto sem amostras não permite afirmar acerto ou superioridade estatística.']}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default=str(ROOT/'validacao_atlas.json'))
    parser.add_argument('--out', default=str(ROOT/'calibracao_atlas.json'))
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding='utf-8'))
    result = calibrate(report)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Calibração descritiva gerada: {args.out} | grupos: {len(result['groups'])} | limiar mantido: ±20")

if __name__ == '__main__':
    main()
