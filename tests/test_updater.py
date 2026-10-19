import importlib.util
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('updater',str(Path(__file__).resolve().parents[1]/'scripts'/'update_literature.py'))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class MetadataTests(unittest.TestCase):
    def test_doi_normalization(self):
        self.assertEqual(module.normalize_doi('HTTPS://DOI.ORG/10.1039/D3EY00309D'), '10.1039/d3ey00309d')
        self.assertEqual(module.normalize_doi('doi: 10.1021/acs.test '), '10.1021/acs.test')

    def test_abstract_reconstruction(self):
        self.assertEqual(module.text_abstract({'bio-oil':[0],'catalysis':[2],'for':[1]}),'bio-oil for catalysis')

    def test_classification(self):
        info=module.detect('Non-thermal plasma catalyst for bio-oil upgrading','DBD upgrading of pyrolysis oil')
        self.assertIn('低温等离子体',info['directions'])
        self.assertTrue(info['accepted'])
        info2=module.detect('Electrochemical conversion of bio-oil','Electrocatalytic hydrogenation')
        self.assertIn('电催化',info2['directions'])

    def test_reject_unrelated(self):
        self.assertFalse(module.detect('Machine learning for cancer','Clinical therapy') ['accepted'])

    def test_merge_preserves_first_seen(self):
        record=module.common_record('Bio-oil catalytic upgrading','Abstract','10.1234/abc',[], 'Journal','2026-01-02','Crossref','', '热催化')
        self.assertIsNotNone(record)
        record['first_seen_at']='2025-10-01T01:02:03Z'
        r2={**record,'sources':['OpenAlex'],'first_seen_at':'2026-10-01T01:02:03Z'}
        result=module.merge(record,r2)
        self.assertEqual(result['first_seen_at'],'2025-10-01T01:02:03Z')
        self.assertEqual(set(result['sources']), {'OpenAlex','Crossref'})

    def test_run_success_and_api_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'data.json'
            cfg=Path(tmp)/'config.json'
            db.write_text(json.dumps({'papers':[],'source_status':'not_run'}),encoding='utf-8')
            cfg.write_text(json.dumps({'daily_lookback_days':30,'first_run_lookback_days':90,'max_per_topic_per_source':5,'max_stored_papers':100,'topics':[{'id':'test','query':'bio-oil hydrodeoxygenation catalyst','direction':'热催化'}]}),encoding='utf-8')
            sample=module.common_record('Bio-oil hydrodeoxygenation catalyst','', '10.1234/test', ['Test A'], 'Journal X','2026-10-17','OpenAlex','','热催化')
            with patch.object(module,'DB',db),patch.object(module,'TOPICS',cfg),patch.object(module,'openalex',return_value=iter([sample])),patch.object(module,'crossref',side_effect=RuntimeError('simulated API failure')),patch.object(module.time,'sleep',return_value=None):
                self.assertEqual(module.run(),0)
                d=json.loads(db.read_text())
                self.assertEqual(d['source_status'],'partial')
                self.assertEqual(d['new_added_count'],1)
                self.assertEqual(d['papers'][0]['doi'],'10.1234/test')
                self.assertTrue(d['last_success'])

    def test_all_failed_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'data.json'
            cfg=Path(tmp)/'config.json'
            original='{"papers":[],"last_success":"2026-01-01T00:00:00Z"}'
            db.write_text(original,encoding='utf-8')
            cfg.write_text(json.dumps({'daily_lookback_days':30,'first_run_lookback_days':90,'max_per_topic_per_source':5,'max_stored_papers':100,'topics':[{'id':'test','query':'bio-oil','direction':'热催化'}]}),encoding='utf-8')
            with patch.object(module,'DB',db),patch.object(module,'TOPICS',cfg),patch.object(module,'openalex',side_effect=RuntimeError('API unavailable')),patch.object(module,'crossref',side_effect=RuntimeError('API unavailable')),patch.object(module.time,'sleep',return_value=None):
                self.assertEqual(module.run(),2)
                self.assertEqual(db.read_text(),original)

if __name__=='__main__': unittest.main()