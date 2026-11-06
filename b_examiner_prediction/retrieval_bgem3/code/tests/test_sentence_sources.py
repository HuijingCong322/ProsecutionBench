"""Leakage/provenance breaks that must be rejected before any embedding."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def module():
 import b_sentence_sources
 return b_sentence_sources

def test_source_module_exists():
 assert (Path(__file__).resolve().parents[1]/'b_sentence_sources.py').is_file()

def test_future_publication_and_exact_historical_cutoff_excluded():
 m=module()
 assert m.date_allowed('2015-01-01','2014-12-31','2015-02-01') is False
 assert m.date_allowed('2015-01-01','2015-01-01','2015-01-01') is False
 assert m.date_allowed('2015-01-01','2015-01-01','2015-02-01') is True

def test_catalog_date_conflict_fails_closed():
 m=module()
 with pytest.raises(ValueError,match='catalog'):
  m.check_catalog('2014-01-01','CLM','abc',{'abc':[{'official_date':'2014-02-01','doc_code':'CLM'}]})

def test_d_pool_keeps_allowance_and_picks_episode_without_outcome_preference():
 m=module()
 def row(e,reply,typ):return {'sample_id':'S','variant':'own','cutoff':'2015-01-01','app_id':'H','family_root':'F','examiner_id':'E','episode_id':e,'reply_date':reply,'next_observed':'True','next_signed_ok':'True','next_type_cut':typ}
 masters={'z':{'prior_signed':'true','next_signed':'','next_date':'2014-10-01','prior_date':'2014-01-01'},'a':{'prior_signed':'true','next_signed':'true','next_date':'2014-11-01','prior_date':'2014-01-01'}}
 selected,ex=m.map_pool([row('a','2014-08-01','final_rejection'),row('z','2014-07-01','allowance')],masters,'S','own','2015-01-01',{'E'},set(),set())
 assert [r['episode_id'] for r in selected]==['z']

def test_d_pool_excludes_other_examiner_future_and_benchmark_family():
 m=module()
 r={'sample_id':'S','variant':'own','cutoff':'2015-01-01','app_id':'H','family_root':'F','examiner_id':'E','episode_id':'e','reply_date':'2014-07-01','next_observed':'True','next_signed_ok':'True'}
 master={'e':{'prior_signed':'false','next_signed':'true','next_date':'2014-10-01','prior_date':'2014-01-01'}}
 assert m.map_pool([r],master,'S','own','2015-01-01',{'E'},set(),set())[0]==[]
 master['e']['prior_signed']='true'
 assert m.map_pool([r],master,'S','own','2015-01-01',{'E'},set(),{'F'})[0]==[]
 master['e']['next_date']='2015-01-01'
 assert m.map_pool([r],master,'S','own','2015-01-01',{'E'},set(),set())[0]==[]

def test_claims_cancelled_and_empty_json_do_not_become_technical_text(tmp_path):
 m=module();p=tmp_path/'claims.json';p.write_text('[{"number":"1","status":"canceled","text":"future leak"},{"number":null,"text":""},{"number":"2","status":"original","text":"A turbine."}]')
 assert m.read_technical(p)=='A turbine.'

def test_publication_without_eligible_date_is_not_read(tmp_path):
 m=module();d=tmp_path/'apps/H/text';d.mkdir(parents=True);(d/'pgpub_abstract.txt').write_text('future technical secret')
 s=m.SourceSelector(tmp_path,{'H':{'pgpub_date':'2016-01-01'}}, {})
 r=s.history('H','2014-01-01','2015-01-01')
 assert r['text']=='' and 'abstract' in r['missing_fields']

def test_numeric_only_claim_extraction_is_missing_text(tmp_path):
 m=module();p=tmp_path/'claims.json';p.write_text('[{"number":"1","status":"","text":"10"}]')
 assert m.read_technical(p)==''

def test_sanitized_reply_code_uses_catalog_not_first_underscore():
 m=module();catalog={'HUEDX97ZPXXIFW3':[{'official_date':'2014-04-24','doc_code':'A...'}]}
 assert m.parse_record_filename('2014-04-24_A____HUEDX97ZPXXIFW3.txt',catalog)==('2014-04-24','A...','HUEDX97ZPXXIFW3')

def test_later_readable_episode_is_used_when_earliest_has_no_technical_text():
 # Real corpus regression: first D-eligible reply predates readable technical sources.
 m=module()
 if not (m.A/'cases.csv').is_file():
  pytest.skip('Requires the separately shared private A/D corpus and frozen release')
 c=m.Corpus();case=next(r for r in c.cases if r['sample_id']=='13421826')
 pool,_=c.pool(case,'artunit');app=[x for x in pool if x['episode']['app_id']=='13464305']
 assert len(app)==1 and app[0]['episode']['reply_date']=='2013-03-07'

def test_target_manifest_cannot_misdeclare_filename_date(tmp_path):
 m=module();d=tmp_path/'apps/H/text';d.mkdir(parents=True);p=d/'2013-01-01_CLM_d.claims.json';p.write_text('[{"text":"A wind turbine."}]')
 sel=m.SourceSelector(tmp_path);sel.catalog=lambda app:{'d':[{'official_date':'2014-01-01','doc_code':'CLM'}]}
 with pytest.raises(ValueError,match='catalog'):
  sel.source(p,'2014-01-01','CLM','d')

def test_known_svg_rendering_metadata_removed_but_claim_content_preserved(tmp_path):
 m=module();p=tmp_path/'claims.json';p.write_text('[{"text":"SVG13826252.12-16-2013.HPA6OWO8PXXIFW3.CLM_8911359.2.301.298.1006.342.svg0.1472.35DrawingBlack and white 1. A plasma gun with a water supply."}]')
 assert m.read_technical(p)=='1. A plasma gun with a water supply.'

@pytest.mark.parametrize('marker',[
'SVG13060040.09-26-2014.I0JYPE5NPXXIFW3.CLM_30096115.1.300.309.1349.435.svg0.423.497ChemistryBlack and white ',
'SVG 13404402.01-27-2014.HQYBEPS9PXXIFW3.CLM.1.svg 0.16 5.64 Black and white ',
'SVG123.01-01-2013.D.CLM_1.2.svg0.23GraphBlack and white ',
'SVG123.01-01-2013.D.CLM_1.2.svg0.23TableBlack and white ',
'SVG123.01-01-2013.D.CLM_1.2.svg0.23MathsBlack and white ',
'SVG123.01-01-2013.D.CLM_1.2.svg0.23DNABlack and white '])
def test_all_observed_svg_placeholder_classes_are_removed(tmp_path,marker):
 m=module();p=tmp_path/'claims.json';import json
 p.write_text(json.dumps([{'text':'A rotor '+marker+'with a blade.'}]))
 assert m.read_technical(p)=='A rotor with a blade.'

def test_adjacent_svg_placeholders_and_plain_abstract_are_cleaned(tmp_path):
 m=module();marker='SVG123.D.CLM_1.2.svg0.23ChemistryBlack and white'
 p=tmp_path/'claims.json';import json;p.write_text(json.dumps([{'text':'wind'+marker+marker+'turbine'}]))
 assert m.read_technical(p)=='wind turbine'
 a=tmp_path/'abstract.txt';a.write_text('A composition '+marker+' containing hydrogen.')
 assert m.read_technical(a)=='A composition containing hydrogen.'

@pytest.mark.parametrize('metadata',['Examiner: EXAMPLE, PERSON','GROUP ART UNIT: 3765','Response to Office Action','35 U.S.C. 112; the Examiner alleges'])
def test_prosecution_metadata_in_claim_file_is_rejected_not_embedded(tmp_path,metadata):
 m=module();p=tmp_path/'claims.json';import json
 p.write_text(json.dumps([{'text':'A mechanical turbine. '+metadata}]))
 assert m.read_technical(p)==''
