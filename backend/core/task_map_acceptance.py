"""Attach actual assistant acceptance evidence without upgrading unrelated flows."""
import json
from pathlib import Path

def apply_acceptance(data):
    suite=json.loads((Path(__file__).parent/'data'/'assistant_acceptance.json').read_text())
    data['planning']['assistant_acceptance']=suite
    data['version']='2026-10-27-v5-assistant-acceptance'
    data['planning']['evidence'].append(dict(id='E13',kind='明确标准的隔离回归与真实模型复跑',title='13组助手任务验收',detail=suite['scope'],path=suite['report']))
    for task in data['tasks']:
        task['acceptance_case_ids']=[c['id'] for c in suite['cases'] if task['id'] in c['task_ids']]
    return data
