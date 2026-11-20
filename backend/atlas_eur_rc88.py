#!/usr/bin/env python3
"""Atlas EUR RC8.8: audit saved RC8.7 raw captures, without PIT claims."""
import argparse, hashlib, json, re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

VERSION='eur-rc8.8-raw-integrity-concept-audit-0.8.8'
FACTORS=('inflation','rates','unemployment','activity')
EXPECTED={'UNRATE':('2025-11-01','4.6'),'DFEDTARL':('2026-09-17','3.75'),
          'DFEDTARU':('2026-09-17','4'),'ECBDFR':('2026-09-16','2.5'),
          'INDPRO':('2026-09-01','103.8458')}
CONCEPTS={
 'UNRATE':('US','civilian unemployment rate','percent','seasonally adjusted'),
 'DFEDTARL':('US','Federal Reserve target range lower bound','percent','not applicable'),
 'DFEDTARU':('US','Federal Reserve target range upper bound','percent','not applicable'),
 'ECBDFR':('EA','ECB deposit facility rate','percent','not applicable'),
 'INDPRO':('US','industrial production index','index 2017=100','seasonally adjusted')}
RELEASE_EXPECTATIONS={
 'US_UNRATE_2025-11_BLS':[('4.6',r'(?<!\d)4[.,]6\s*%')],
 'US_FOMC_2026-09-16':[('3.75',r'(?<!\d)3[.,]75'),('4.00',r'(?<!\d)4[.,]00')],
 'EU_ECB_2026-09-10':[('2.50',r'(?<!\d)2[.,]50')],
 'EU_HICP_2026-09_FLASH':[('3.8',r'(?<!\d)3[.,]8\s*%')],
 'EU_HICP_2026-09_FULL':[('3.8',r'(?<!\d)3[.,]8\s*%')],
 'EU_HICP_2026-10_FLASH':[('4.0',r'(?<!\d)4[.,]0\s*%')],
 'EU_INDUSTRY_2026-09':[('0.2',r'(?<!\d)0[.,]2\s*%')]}
class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript') and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)
def visible_text(raw):
    parser=TextExtractor();parser.feed(raw.decode('utf-8','replace'))
    return re.sub(r'\s+',' ',' '.join(parser.parts)).strip()
def inspect_record(rec,base):
    out={'event_id':rec.get('event_id'),'evidence_kind':rec.get('evidence_kind'),
         'series_id':rec.get('series_id'),'integrity':'missing_capture',
         'first_dissemination_verified':False,'original_full_vintage_verified':False,
         'point_in_time_usable':False}
    capture=rec.get('raw_capture')
    if not capture:return out
    relative=Path(capture.get('path',''))
    # Archives must be inside the current working directory, never arbitrary absolute paths.
    if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0]!='eur_rc87_archive':
        out['integrity']='invalid_path';return out
    target=(base/relative).resolve();root=(base/'eur_rc87_archive').resolve()
    if not target.is_relative_to(root):out['integrity']='invalid_path';return out
    if not target.is_file():return out
    raw=target.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    out['sha256_match']=sha==capture.get('sha256')
    out['size_match']=len(raw)==capture.get('size_bytes')
    out['integrity']='verified' if out['sha256_match'] and out['size_match'] else 'mismatch'
    out['bytes_checked']=len(raw)
    if out['integrity']!='verified':return out
    if rec.get('evidence_kind')=='alfred_date_granularity_vintage':
        try:
            data=json.loads(raw)
            obs=data.get('observations',[])
            series=rec.get('series_id');expect=EXPECTED.get(series)
            out['parsed_observations']=[{'date':x.get('date'),'value':x.get('value')} for x in obs[:5]]
            out['matches_prior_rc87_observations']=out['parsed_observations'][:3]==rec.get('observations',[])
            out['expected_observation_present']=bool(expect and any(x.get('date')==expect[0] and x.get('value')==expect[1] for x in obs))
            out['concept_profile']=dict(zip(('geography','concept','unit','seasonal_adjustment'),CONCEPTS.get(series,('unknown',)*4)))
            out['source_response_error']=bool(data.get('error_code'))
        except (ValueError,TypeError,AttributeError):out['parse_error']='invalid_json'
    elif rec.get('evidence_kind')=='official_archived_release_page':
        text=visible_text(raw)
        checks=[]
        for label,pattern in RELEASE_EXPECTATIONS.get(rec.get('event_id'),[]):
            found=bool(re.search(pattern,text,re.IGNORECASE))
            checks.append({'expected_value':label,'found_somewhere_in_document':found,
                           'headline_context_verified':False,'concept_unit_mapping_verified':False})
        out['visible_text_characters']=len(text)
        out['value_presence_checks']=checks
        out['value_presence_is_not_headline_validation']=True
    return out

def build(source,base):
    records=source.get('records',[])
    if not (source.get('model_version','').startswith('eur-rc8.7-') and source.get('input_valid') is True
            and len(records)==12 and source.get('eligible_count')==0 and source.get('coverage')==0.0
            and source.get('relative_score') is None and not source.get('point_in_time_integrity_verified',True)
            and all(not x.get('point_in_time_usable',True) for x in records)):
        raise ValueError('RC8.7 input invalid or PIT safety gate failed')
    inspected=[inspect_record(r,base) for r in records]
    valid=sum(x['integrity']=='verified' for x in inspected)
    mismatched=sum(x['integrity']=='mismatch' for x in inspected)
    missing=sum(x['integrity']=='missing_capture' for x in inspected)
    absent=sum(x['integrity']=='invalid_path' for x in inspected)
    return {'model_version':VERSION,'asset':'EUR/USD','module':'raw_integrity_and_concept_audit',
            'asof_utc':datetime.now(timezone.utc).isoformat(),'input_valid':True,
            'records_reviewed':len(inspected),'raw_files_integrity_verified':valid,
            'raw_files_missing':missing,'raw_files_mismatched':mismatched,'raw_files_invalid_path':absent,
            'release_value_presence_checks':sum(len(x.get('value_presence_checks',[])) for x in inspected),
            'release_value_presence_found':sum(c['found_somewhere_in_document'] for x in inspected for c in x.get('value_presence_checks',[])),
            'alfred_observations_matching_prior':sum(x.get('matches_prior_rc87_observations') is True for x in inspected),
            'alfred_expected_observations_found':sum(x.get('expected_observation_present') is True for x in inspected),
            'records':inspected,'non_equivalence_findings':[
                {'left':'US INDPRO','right':'Eurostat euro-area industrial production month-over-month',
                 'reason':'Different geography and unit: US 2017=100 index versus EA monthly percent change',
                 'concept_unit_equivalent':False},
                {'left':'FOMC target bounds','right':'ECB deposit facility rate',
                 'reason':'Different central banks and policy-rate definitions; no direct equality',
                 'concept_unit_equivalent':False}],
            'concept_and_unit_mapping_verified':False,'independent_first_dissemination_timestamps_verified':0,
            'original_full_first_release_datasets_verified':0,'verified_point_in_time_events':0,
            'point_in_time_integrity_verified':False,'eligibility':{f:False for f in FACTORS},
            'eligible_count':0,'coverage':0.0,'relative_score':None,
            'horizons':{'1d':{'score':None},'5d':{'score':None}},
            'point_in_time_backtest_authorized':False,'signals_generated':False,
            'database_writes':False,'production_change_authorized':False,
            'source_code_modified':False,'prospective_capture_active':False,
            'methodology_note':'Matching SHA256 proves integrity against RC8.7 manifest, not authenticity at original publication. Value presence anywhere on a page does not prove headline or unit. Current archive capture is not an original PIT vintage.',
            'next_step':'Inspect contextual release tables and obtain independently timestamped first-release archives.'}
def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        base=Path(temp);folder=base/'eur_rc87_archive';folder.mkdir()
        payload=b'{"observations":[{"date":"2025-11-01","value":"4.6"}]}'
        (folder/'alfred_UNRATE.json').write_bytes(payload)
        record={'event_id':'US_UNRATE_2025-11_BLS','evidence_kind':'alfred_date_granularity_vintage',
                'series_id':'UNRATE','observations':[{'date':'2025-11-01','value':'4.6'}],
                'point_in_time_usable':False,'raw_capture':{'path':'eur_rc87_archive/alfred_UNRATE.json',
                'sha256':hashlib.sha256(payload).hexdigest(),'size_bytes':len(payload)}}
        sample={'model_version':'eur-rc8.7-test','input_valid':True,'eligible_count':0,'coverage':0.0,
                'relative_score':None,'point_in_time_integrity_verified':False,
                'records':[record]+[{'point_in_time_usable':False} for _ in range(11)]}
        result=build(sample,base)
        assert result['raw_files_integrity_verified']==1 and result['raw_files_missing']==11
        assert result['alfred_expected_observations_found']==1
        assert not result['point_in_time_integrity_verified'] and not result['signals_generated']
    print('RC88_SELF_TEST_OK')
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='eur_rc87_result.json')
    p.add_argument('--output',default='eur_rc88_result.json')
    p.add_argument('--base-dir',default='.')
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test();return
    src=json.loads(Path(a.input).read_text(encoding='utf-8'))
    result=build(src,Path(a.base_dir))
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('RC88_OK',result['raw_files_integrity_verified'],result['raw_files_missing'],result['raw_files_mismatched'])
if __name__=='__main__':main()
