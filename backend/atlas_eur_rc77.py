#!/usr/bin/env python3
"""Atlas EUR RC7.7 — contextual evidence triage, read-only and fail-closed.
Input: RC7.6 evidence JSON. No network requests, scores, or database writes.
"""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

VERSION='eur-rc7.7-contextual-evidence-triage-0.7.7'
FACTORS=('inflation','rates','unemployment','activity')

def classify(factor, label, candidate):
    kind=candidate.get('kind','')
    context=' '.join(str(candidate.get('context','')).split())
    matched=str(candidate.get('matched_text',''))
    s=context.lower(); l=label.lower()
    category='unrelated_or_ambiguous'
    reason='No sufficiently specific event linkage in the extracted context.'
    confidence='low'
    if factor=='inflation':
        if 'geographical information' in s or 'december 31, 2025' in matched.lower():
            category='geographic_methodology_context'; reason='Euro-area membership or geography, not release date.'; confidence='high'
        elif kind=='percent_candidate' and ('annual inflation' in s or 'euro area' in s):
            category='inflation_value_candidate'; reason='Potential headline, but target period and series vintage must be verified.'; confidence='medium'
    elif factor=='rates':
        if 'minutes:' in s or 'minutes' in s and 'released' in s:
            category='fomc_minutes_release'; reason='Minutes publication is not the FOMC decision announcement.'; confidence='high'
        elif 'statement' in s and 'fomc' in s:
            category='policy_statement_reference'; reason='Possible statement reference; needs individual dated statement.'; confidence='medium'
        elif 'effective' in s:
            category='effective_rate_reference'; reason='Effective date cannot establish announcement timestamp.'; confidence='medium'
    elif factor=='unemployment':
        if 'embargoed until' in s and kind=='time_candidate':
            category='official_embargo_time_candidate'; reason='Official release embargo time; not independently proven actual dissemination time.'; confidence='high'
        elif 'scheduled to be released' in s:
            category='future_scheduled_release'; reason='Future schedule in document, not the current report release.'; confidence='high'
        elif 'unemployment rate' in s and kind=='percent_candidate':
            category='unemployment_headline_candidate'; reason='Unemployment value in release text; must link exact period and first published vintage.'; confidence='medium'
        elif 'survey' in s and ('suspended' in s or 'shutdown' in s):
            category='survey_interruption_context'; reason='Survey continuity or government shutdown, not publication timestamp.'; confidence='high'
        elif any(w in s for w in ('response rate','overlap','confidence level','participation rate','whites','blacks','adult men','adult women','teenagers')):
            category='secondary_survey_statistic'; reason='Survey methodology or subgroup statistic, not target headline.'; confidence='high'
        elif kind=='date_candidate' and ('last modified' in s or 'revised' in s):
            category='revision_or_page_update'; reason='Revision/page-update date is not original first release.'; confidence='high'
    elif factor=='activity':
        if 'monthly releases are issued at' in s and kind=='time_candidate':
            category='scheduled_g17_release_time'; reason='General G.17 schedule; individual actual release not established.'; confidence='high'
        elif 'last update:' in s:
            category='page_update_date'; reason='Website update, not individual economic release.'; confidence='high'
        elif 'retired' in s or 'removal' in s:
            category='website_maintenance'; reason='Website feature notice, not economic release.'; confidence='high'
    # Generic fallback never upgrades evidence.
    if category=='unrelated_or_ambiguous' and kind=='percent_candidate':
        category='unlinked_percentage'; reason='Percentage lacks validated headline, period and release link.'
    elif category=='unrelated_or_ambiguous' and kind=='date_candidate':
        category='unlinked_date'; reason='Date lacks validated event-specific linkage.'
    elif category=='unrelated_or_ambiguous' and kind=='time_candidate':
        category='unlinked_time'; reason='Time lacks validated event-specific linkage.'
    return {'kind':kind,'matched_text':matched,'context':context,'classification':category,
            'classification_confidence':confidence,'rationale':reason,
            'document_label':label,'factor':factor,
            'event_specific_document_verified':False,
            'actual_publication_timestamp_verified':False,
            'first_release_value_verified':False,
            'point_in_time_usable':False}

def audit(source):
    if not isinstance(source,dict) or not str(source.get('model_version','')).startswith('eur-rc7.6-') or not source.get('input_valid'):
        raise ValueError('Unexpected RC7.6 input')
    if (source.get('asset')!='EUR/USD' or source.get('eligible_count')!=0 or source.get('relative_score') is not None
        or source.get('verified_point_in_time_events')!=0 or source.get('coverage')!=0.0
        or any(source.get(k) for k in ('signals_generated','database_writes','production_change_authorized','point_in_time_backtest_authorized'))):
        raise ValueError('Unsafe RC7.6 input')
    docs=source.get('documents')
    if not isinstance(docs,list) or len(docs)<7 or any(d.get('factor') not in FACTORS for d in docs):
        raise ValueError('Missing or invalid source documents')
    events=source.get('publication_events')
    if not isinstance(events,list) or not events or any(e.get('point_in_time_usable') or e.get('available_asof_utc') is not None for e in events):
        raise ValueError('Unsafe publication events')
    outdocs=[]; classifications={}; total=0
    for d in docs:
        if d.get('point_in_time_usable') or d.get('publication_timestamp_verified') or d.get('first_release_value_verified'):
            raise ValueError('Unexpected verified source document')
        candidates=d.get('candidates',[])
        if not isinstance(candidates,list): raise ValueError('Invalid candidate list')
        classified=[classify(d['factor'],d.get('label',''),c) for c in candidates]
        for c in classified:
            classifications[c['classification']]=classifications.get(c['classification'],0)+1
        total+=len(classified)
        outdocs.append({'factor':d['factor'],'label':d.get('label'), 'source_url':d.get('source_url'),
                        'retrieval_status':d.get('status'), 'retrieved_sha256':d.get('sha256'),
                        'candidates_classified':len(classified),'evidence':classified,
                        'event_specific_document_verified':False,'point_in_time_usable':False})
    result={'model_version':VERSION,'asof_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'asset':'EUR/USD','module':'contextual_evidence_triage','input_model_version':source['model_version'],
        'input_valid':True,'documents_reviewed':len(outdocs),'documents_retrieved':sum(d['retrieval_status']=='retrieved' for d in outdocs),
        'candidate_count':total,'classification_counts':dict(sorted(classifications.items())),
        'documents':outdocs,'publication_events':[{**e,'release_timestamp_utc':None,
            'release_timestamp_verified':False,'first_release_value':None,'first_release_value_verified':False,
            'available_asof_utc':None,'point_in_time_usable':False} for e in events],
        'factor_audit':{f:{'documents_reviewed':sum(d['factor']==f for d in outdocs),
            'candidate_count':sum(d['candidates_classified'] for d in outdocs if d['factor']==f),
            'eligible':False} for f in FACTORS},
        'verified_point_in_time_events':0,'historical_first_release_vintages_verified':False,
        'historical_release_timestamps_verified':False,'point_in_time_integrity_verified':False,
        'eligibility':{f:False for f in FACTORS},'eligible_count':0,'coverage':0.0,
        'relative_score':None,'horizons':{'1d':{'score':None},'5d':{'score':None}},
        'point_in_time_backtest_authorized':False,'signals_generated':False,
        'database_writes':False,'production_change_authorized':False,'source_code_modified':False,
        'next_step':'Find event-specific archived documents, verify original values and official release time with independent evidence.',
        'limitations':['Classification is heuristic, not a factual authentication of historical releases.',
                       'Embargo and scheduled time do not independently prove actual dissemination time.',
                       'Generic index pages cannot validate a specific economic event.',
                       'No scoring, trading signals, backtests or production writes.']}
    return result

def self_test():
    cases=[('rates','FOMC','date_candidate','October 07, 2026','Minutes: PDF | HTML (Released October 07, 2026)','fomc_minutes_release'),
        ('unemployment','BLS','time_candidate','8:30 a.m.','Transmission of material in this news release is embargoed until 8:30 a.m. (ET) Tuesday','official_embargo_time_candidate'),
        ('unemployment','BLS','percent_candidate','4.6 percent','In November the unemployment rate, at 4.6 percent, was little changed','unemployment_headline_candidate'),
        ('activity','G17','time_candidate','9:15 a.m.','The monthly releases are issued at 9:15 a.m.','scheduled_g17_release_time'),
        ('inflation','Eurostat','date_candidate','December 31, 2025','Geographical information Up to December 31, 2025 the euro area included','geographic_methodology_context')]
    for f,l,k,m,c,expected in cases:
        r=classify(f,l,{'kind':k,'matched_text':m,'context':c})
        assert r['classification']==expected,(r,expected)
        assert not r['point_in_time_usable']
    sample={'model_version':'eur-rc7.6-test','asset':'EUR/USD','input_valid':True,'eligible_count':0,
        'coverage':0.0,'relative_score':None,'verified_point_in_time_events':0,
        'documents':[{'factor':f,'label':l,'status':'retrieved','candidates':[{'kind':k,'matched_text':m,'context':c}]} for f,l,k,m,c,_ in cases]+
                    [{'factor':'rates','status':'retrieved','candidates':[]},{'factor':'activity','status':'retrieved','candidates':[]}],
        'publication_events':[{'factor':'inflation','available_asof_utc':None,'point_in_time_usable':False}]}
    r=audit(sample)
    assert r['candidate_count']==5 and r['eligible_count']==0 and not r['signals_generated']
    assert all(x['available_asof_utc'] is None for x in r['publication_events'])
    print('RC77_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='eur_rc76_result.json')
    p.add_argument('--output',default='eur_rc77_result.json');p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test: self_test();return
    result=audit(json.loads(Path(a.input).read_text(encoding='utf-8')))
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"RC7.7: {result['documents_reviewed']} docs; {result['candidate_count']} candidates; PIT=0")
if __name__=='__main__':main()
