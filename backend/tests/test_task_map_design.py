import unittest
from core.task_map import catalog

class TaskMapDesignTests(unittest.TestCase):
    def setUp(self):
        self.map=catalog();self.tasks={t['id']:t for t in self.map['tasks']}
    def test_task_ids_unique_and_stage_ownership_complete(self):
        self.assertEqual(len(self.tasks),len(self.map['tasks']))
        flattened=[id for stage in self.map['stage_details'] for id in stage['task_ids']]
        self.assertEqual(sorted(flattened),sorted(self.tasks))
        for stage in self.map['stage_details']:
            for id in stage['task_ids']:self.assertEqual(self.tasks[id]['stage'],stage['id'])
    def test_all_tasks_have_inputs_output_current_support_and_evidence_boundary(self):
        for task in self.tasks.values():
            for field in ['inputs','output','acceptance','source','frequency','current_support','gap','verification','priority_reason','validation']:
                self.assertTrue(task[field],(task['id'],field))
            self.assertIn('尚无',task['frequency'])
            for prerequisite in task['depends_on']:self.assertIn(prerequisite,self.tasks)
    def test_added_gaps_do_not_claim_local_completion(self):
        self.assertEqual(sum(t['availability']=='local' for t in self.tasks.values()),24)
        for id in ['F04','F08','F11','F12','F13']:
            self.assertNotEqual(self.tasks[id]['availability'],'local')
            self.assertEqual(self.tasks[id]['priority_status'],'建议，待业务验证')
            self.assertIn('待真实业务人员确认',self.tasks[id]['source'])
    def test_repaired_tasks_are_now_local_and_describe_remaining_limits(self):
        for id in ['F06','F07','F03','F05','F09','F10','F14']:
            self.assertEqual(self.tasks[id]['availability'],'local')
            self.assertEqual(self.tasks[id]['priority'],'baseline')
            self.assertTrue(self.tasks[id]['gap'])
    def test_scenario_decisions_handoffs_and_task_backlinks_are_valid(self):
        self.assertEqual(len(self.map['scenarios']),13)
        roles={r['id'] for r in self.map['roles']}
        for scenario in self.map['scenarios']:
            self.assertTrue(scenario['decisions'])
            for id in scenario['task_ids']:
                self.assertIn(id,self.tasks);self.assertIn(scenario['id'],self.tasks[id]['scenario_ids'])
            for decision in scenario['decisions']:
                for field in ['question','yes','no','refs']:self.assertTrue(decision[field])
                for id in decision['refs']:self.assertIn(id,self.tasks)
            for handoff in scenario['handoffs']:
                self.assertIn(handoff['from_role'],roles);self.assertIn(handoff['to_role'],roles);self.assertIn(handoff['task'],self.tasks)
    def test_priority_and_metrics_explain_assumptions_and_unimplemented_result(self):
        self.assertIn('尚未完成真实客服访谈',self.map['research']['limits'])
        self.assertEqual(len(self.map['research']['questions']),6)
        for t in self.tasks.values():self.assertIn(t['priority'],self.map['priority_guide'])
        for metric in self.map['metrics']:
            self.assertTrue(metric['definition']);self.assertTrue(metric['status'])
            for id in metric['tasks']:self.assertIn(id,self.tasks)
    def test_export_data_is_a_fresh_snapshot(self):
        self.map['tasks'][0]['steps'].append('accidental mutation')
        self.assertNotIn('accidental mutation',catalog()['tasks'][0]['steps'])
