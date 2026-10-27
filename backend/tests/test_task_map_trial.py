import unittest
from core.task_map import catalog
class TrialMapTests(unittest.TestCase):
 def setUp(self):
  self.map=catalog();self.plan=self.map['planning'];self.tasks={t['id']:t for t in self.map['tasks']};self.flows={f['id']:f for f in self.plan['flows']}
 def test_observed_defects_are_not_claimed_fixed(self):
  self.assertEqual({i['id'] for i in self.plan['latest_trial']['issues']},{'G01','G02','G03','G04'})
  for issue in self.plan['latest_trial']['issues']:
   self.assertEqual(issue['state'],'已复现，待修复');self.assertTrue(issue['steps']);self.assertTrue(issue['observed']);self.assertTrue(issue['expected'])
   for task in issue['tasks']:self.assertIn(issue['id'],self.tasks[task]['known_issue_ids'])
  for id in ['C06','C16','C18']:self.assertEqual(self.flows[id]['status'],'partial')
 def test_exception_scenarios_trace_to_tasks_and_acceptance(self):
  self.assertEqual(len(self.map['scenarios']),13);self.assertEqual(len(self.plan['flows']),19)
  for s in self.map['scenarios']:
   for id in s['task_ids']:self.assertIn(s['id'],self.tasks[id]['scenario_ids'])
  stories={s['id']:s for s in self.plan['stories']}
  for id in ['N13','N16']:
   self.assertEqual(stories[id]['implementation'],'planned');self.assertEqual(stories[id]['release_id'],'R2')
 def test_translation_reference_and_reply_are_distinct_tasks(self):
  self.assertIn('已保存',self.tasks['T04']['output']);self.assertIn('不追加客户回复',self.tasks['T04']['current_support']);self.assertIn('外语译稿',self.tasks['T07']['current_support'])
 def test_trial_is_not_presented_as_customer_research_or_full_production_coverage(self):
  trial=self.plan['latest_trial'];self.assertIn('不是客户访谈',trial['method']);self.assertEqual(len(trial['checks']),43);self.assertTrue(all(c['method'] in {'browser','live-api','interface-review'} for c in trial['checks']));self.assertEqual(len(trial['limitations']),3)
 def test_issue_evidence_is_a_fresh_snapshot(self):
  self.plan['latest_trial']['issues'][0]['title']='mutated';self.assertNotEqual(catalog()['planning']['latest_trial']['issues'][0]['title'],'mutated')
