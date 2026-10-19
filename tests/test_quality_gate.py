"""Offline tests for conservative literature triage.
The classifier must NEVER equate metadata screening with full-text verification.
"""
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('updater',str(Path(__file__).resolve().parents[1]/'scripts'/'update_literature.py'))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class QualityGateTests(unittest.TestCase):
 def check(self,title,tier):
  got=mod.classify_scope(title,'')
  self.assertEqual(got['screening_tier'],tier)
  self.assertEqual(got['fulltext_status'],'全文待核验')
  self.assertIn('NOT full-text verified',got['screening_method'])
 def test_jet_fuel_plasma(self):
  self.check('Non-thermal plasma catalysis of bio-oil to jet fuel','核心相关')
 def test_microalgae_hdn(self):
  self.check('Hydrodeoxygenation of microalgae HTL biocrude over Ni-Co catalysts','核心相关')
 def test_model_compound(self):
  self.check('Catalytic hydrodeoxygenation of lignin-derived phenolics','扩展参考')
 def test_pollutant_false_positive(self):
  self.check('Biomass-derived photocatalysts for antibiotic removal','可能不相关')
 def test_saf_background(self):
  self.check('Sustainable aviation fuel combustion characteristics review','背景候选')
 def test_amide_hdn_model(self):
  self.check('Hydrodeoxygenation and hydrodenitrogenation of hexadecanamide over NiMo','扩展参考')

if __name__=='__main__': unittest.main()