import importlib.util
import pathlib
import tempfile
import unittest

M=pathlib.Path(__file__).resolve().parents[1]/'scripts'/'enrich_fulltext.py'
spec=importlib.util.spec_from_file_location('enrich_fulltext',M)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

JATS='''<article><front><article-meta><abstract><p>ABC</p></abstract></article-meta></front><body>
<sec><title>Materials and Methods</title><p>We employed Ni/H-beta catalyst (0.25 g) with a 100 mL stirred autoclave reactor at 320 °C and 3 MPa hydrogen pressure for 6 h.</p></sec>
<sec><title>Results</title><p>The jet-fuel-range cycloalkane fraction was investigated, and oil yield was 40 wt% on a dry carbon basis.</p></sec>
<sec><title>References</title><p>Some other catalyst shows 99% conversion at 500 °C, which should be excluded.</p></sec>
</body></article>'''
class TestFulltext(unittest.TestCase):
    def test_parse_sections(self):
        ps=m.parse_jats(JATS)
        self.assertEqual(len(ps),2)
        self.assertIn('Methods',ps[0]['section'])
    def test_no_reference(self):
        ps=m.parse_jats(JATS)
        self.assertFalse(any('500 °C' in x['text'] for x in ps))
    def test_extraction_is_unreviewed(self):
        f=m.extract_suggestions(m.parse_jats(JATS),'https://europepmc.org/articles/PMC123')
        self.assertIn('rx_reactor',f)
        self.assertIn('rx_temp',f)
        self.assertIn('out_oil',f)
        self.assertFalse(f['rx_temp']['reviewed'])
        self.assertTrue(f['rx_temp']['source'].startswith('https://'))
    def test_no_fabrication(self):
        f=m.extract_suggestions([{'section':'Methods','text':'Nothing relevant here.'}],'https://x.org')
        self.assertNotIn('rx_pressure',f)
    def test_europmc_doi_exact(self):
        m.get_json=lambda url:{'resultList':{'result':[{'doi':'10.1/other','pmcid':'PMC1'},{'doi':'10.1/target','pmcid':'PMC2'}]}}
        self.assertEqual(m.epmc_lookup('10.1/target')['pmcid'],'PMC2')

if __name__=='__main__':unittest.main()