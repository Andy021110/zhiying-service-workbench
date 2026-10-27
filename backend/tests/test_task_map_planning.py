import unittest
from core.task_map import catalog


class PlanningTraceabilityTests(unittest.TestCase):
    def setUp(self):
        self.data=catalog();self.plan=self.data['planning']
        self.tasks={t['id']:t for t in self.data['tasks']}
        self.stories={s['id']:s for s in self.plan['stories']}
        self.evidence={e['id']:e for e in self.plan['evidence']}

    def test_every_task_is_traceable_to_activity_and_story(self):
        self.assertEqual(len(self.tasks),31)
        ids={a['id'] for a in self.plan['activities']}
        for task in self.tasks.values():
            self.assertIn(task['activity_id'],ids)
            self.assertTrue(task['story_ids'])
            for id in task['story_ids']:self.assertIn(task['id'],self.stories[id]['task_ids'])
        flattened=[id for a in self.plan['activities'] for id in a['task_ids']]
        self.assertEqual(sorted(flattened),sorted(self.tasks))
        grouped=[id for g in self.plan['task_groups'] for id in g['task_ids']]
        self.assertEqual(sorted(grouped),sorted(self.tasks))
        for g in self.plan['task_groups']:
            for id in g['task_ids']:
                self.assertEqual(self.tasks[id]['group_id'],g['id'])
                self.assertEqual(self.tasks[id]['activity_id'],g['activity_id'])
        for s in self.stories.values():
            self.assertTrue(s['group_ids']);self.assertTrue(s['role_ids'])
            for id in s['task_ids']:self.assertEqual(self.tasks[id]['activity_id'],s['activity_id'])

    def test_release_membership_is_unique_and_targets_do_not_claim_implemented(self):
        assigned=[]
        for release in self.plan['releases']:
            self.assertTrue(release['goal']);self.assertTrue(release['exit'])
            for id in release['story_ids']:
                assigned.append(id);self.assertEqual(self.stories[id]['release_id'],release['id'])
                self.assertEqual(self.stories[id]['implementation'],'local' if release['id'] in {'R0','R1'} else 'planned')
        self.assertEqual(sorted(assigned),sorted(self.stories))

    def test_acceptance_and_dependencies_are_actionable_without_cycles(self):
        def visit(id,seen):
            self.assertNotIn(id,seen)
            for dep in self.stories[id]['depends_on']:visit(dep,seen|{id})
        for s in self.stories.values():
            self.assertTrue(s['acceptance'])
            for c in s['acceptance']:
                for field in ['given','when','then']:self.assertTrue(c[field])
            visit(s['id'],set())

    def test_flow_conclusions_match_branch_coverage_and_references(self):
        self.assertEqual(len({f['id'] for f in self.plan['flows']}),len(self.plan['flows']))
        for flow in self.plan['flows']:
            self.assertIn(flow['status'],self.plan['legend'])
            self.assertTrue(flow['scope']);self.assertTrue(flow['gap'])
            if flow['status']=='covered':self.assertTrue(all(c['result']=='covered' for c in flow['checks']))
            if flow['status']=='partial':
                self.assertTrue(any(c['result']=='covered' for c in flow['checks']))
                self.assertTrue(any(c['result']!='covered' for c in flow['checks']))
            for id in flow['task_ids']:self.assertIn(id,self.tasks)
            for id in flow['next_story_ids']:self.assertIn(id,self.stories)
            for c in flow['checks']:
                self.assertIn(c['result'],self.plan['legend']);self.assertTrue(c['evidence_ids'])
                for id in c['evidence_ids']:self.assertIn(id,self.evidence)

    def test_manual_customer_result_has_no_channel_prerequisite(self):
        task=self.tasks['F05']
        self.assertEqual(task['availability'],'local')
        self.assertNotIn('F01',task['depends_on'])
        self.assertEqual(self.stories['N01']['depends_on'],['B06'])
        self.assertNotIn('P01',self.stories['N01']['depends_on'])
        self.assertEqual(self.tasks['F01']['availability'],'external')

    def test_snapshot_cannot_mutate_acceptance_evidence_or_flow_truth(self):
        self.plan['stories'][0]['acceptance'][0]['then']='changed'
        self.plan['flows'][0]['checks'][0]['result']='missing'
        self.plan['evidence'][0]['title']='changed'
        fresh=catalog()['planning']
        self.assertNotEqual(fresh['stories'][0]['acceptance'][0]['then'],'changed')
        self.assertEqual(fresh['flows'][0]['checks'][0]['result'],'covered')
        self.assertNotEqual(fresh['evidence'][0]['title'],'changed')

    def test_unmeasured_business_results_remain_unmeasured(self):
        for m in self.plan['metrics']:
            self.assertTrue(m['baseline']);self.assertEqual(m['target'],'业务试用后确定')
        for s in self.stories.values():
            for id in s['evidence_ids']:self.assertIn(id,self.evidence)
            if s['implementation']!='local':self.assertIn('尚未实现或验收',s['acceptance_state'])
