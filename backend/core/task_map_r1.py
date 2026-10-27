"""Update coverage only for the five locally implemented first-batch tasks."""

def apply_r1(data):
    tasks={t['id']:t for t in data['tasks']};plan=data['planning']
    updated={
        'F05':('人工客户结果、发生时间、来源、更正历史和独立跟进；内部结案例外检查',
               '企业退出规则仍需业务定义；无真实渠道回执；无法联系不算客户确认解决'),
        'F09':('逐项材料名称、必要性、负责人、期限、收到/核验/豁免/撤回状态及历史；结案检查必要材料',
               '必要材料模板与豁免权限仍需业务核实；不自动判断材料真实性'),
        'F03':('按事项权限上传、预览/下载PNG/JPEG/WebP/PDF原文件；幂等重试、来源、归档原因与历史',
               '单文件5MB、每事项20个活动凭证；归档保留原文件，自动清理与业务保留期尚未配置'),
        'F14':('从明确关联的缺口和业务引用生成版本回查项；逐项结论、说明、处理人、版本和历史；待办入口',
               '仅覆盖明确关联，不推断所有语义相关事项；不会自动重开、改写采用稿或发送外部提醒'),
        'F10':('更正原题、带原因撤销/恢复、同范围合并与转向；保留来源事项、原文和版本检查',
               '本地空间成员权限规则；正式企业治理仍依赖F12；合并后从目标继续维护')}
    for id,(support,gap) in updated.items():
        t=tasks[id];t.update(availability='local',current_support=support,gap=gap,priority='baseline',
            priority_status='本地已验收，不代表生产可用',source='首批功能本地流程、接口与浏览器验收；待真实业务人员观察',
            verification='核对对应需求故事的验收条件与首批验收证据；不证明真实客户问题解决',
            priority_reason='本轮已补齐本地能力，保留回归检查',validation='业务退出、材料与知识责任规则仍需实际业务确认',
            evidence_ids=['E06','E07','E08'])
    tasks['F03']['steps']=['建立材料项并选择所属事项','上传原始凭证并记录人工来源','授权成员查看/下载并核验，必要时带原因归档']
    tasks['F05']['view']='desk'
    tasks['F03']['exception']='类型/大小/权限不符合时不保存假凭证；新凭证或归档后需重新核验；原文件仍在本机保留'
    tasks['F09']['steps']=['建立材料清单并安排负责人和期限','区分待收集、已收到和已核验','必要材料先核验或带原因豁免；撤回保留历史']
    tasks['F10']['steps']=['核对原问题和全部来源事项','填写更正、撤销或合并原因','保存版本；合并后从原记录打开目标继续维护']
    tasks['F10']['exception']='合并目标需同范围且有效；拒绝自身、循环、过期版本与跨空间操作；不自动结案'
    tasks['F14']['steps']=['从影响事项清单或原事项找到待回查项','核对当前生效依据与原事项','登记已回查、不适用或继续待回查及说明']
    for s in plan['stories']:
        if s['release_id']=='R1':s.update(implementation='local',acceptance_state='首批本地流程已验收；业务规则与生产效果待验证',evidence_ids=['E06','E07','E08'])
    flows={f['id']:f for f in plan['flows']}
    for id in ['C02','C04','C06']:
        f=flows[id];f['status']='covered';f['next_story_ids']=[]
        for c in f['checks']:c.update(result='covered',evidence_ids=['E06','E07'])
    flows['C02']['gap']='本地材料清单、原文件、权限与核验已支持；材料真实性和业务模板仍需人工确认'
    flows['C04']['gap']='缺口治理、生效版本和明确关联事项回查已支持；自动联系与语义影响推断不在本地范围'
    flows['C06']['gap']='人工客户结果及独立跟进已支持；真实渠道送达和业务结案退出规则仍需接入或确认'
    flows['C01']['checks'][-1].update(result='covered',evidence_ids=['E06','E07'])
    flows['C01']['gap']='本地回复准备、客户结果和跟进已有；真实渠道发送/回执仍未接入'
    flows['C01']['next_story_ids']=['P01']
    for r in plan['releases']:
        if r['id']=='R1':r.update(name='第一轮 · 本地记录闭环',state='本地已实现',exit='N01—N05已完成本地流程验收；仍需确认真实业务退出规则、材料模板和凭证保留期。实际发送与平台执行另行接入。')
    for scenario in data['scenarios']:
        for d in scenario['decisions']:
            if scenario['id']=='S01' and d['at']=='F01':d['no']='人工客户结果可登记；真实发送失败/送达回执待接入，保留人工跟进'
            if scenario['id']=='S04' and d['at']=='F10':d['no']='填写原因后更正、撤销或合并缺口，原问题与来源事项保留'
    data['metrics'][0]['status']='人工客户结果和本地结案分开记录；真实渠道回执仍待接入'
    data['metrics'][3]['status']='生效文档与明确关联事项的逐项回查已本地支持；语义影响范围待验证'
    for metric in plan['metrics']:
        if metric['name']=='客户结果完整性':metric['baseline']='已有独立字段与历史，待积累真实业务样本'
        elif metric['name'] in {'材料反复追补次数','知识回查完成情况'}:metric['baseline']='已具备本地记录，真实业务基线待采集'
    plan['evidence'].extend([
        dict(id='E06',kind='首批后端回归',title='结果、材料、附件、缺口治理与回查测试',detail='隔离测试库验证权限、版本冲突、事务持久化、结案约束、合并防循环和明确关联回查；结果见本轮测试记录。',path='outputs/r1/后端测试.txt'),
        dict(id='E07',kind='首批浏览器流程',title='材料→客户结果→缺口合并→版本回查',detail='本地浏览器串联验证首批流程。临时文档元数据不进入检索索引，验收后归档；不证明真实规则正确或客户已解决。',path='outputs/r1/浏览器验收.json'),
        dict(id='E08',kind='首批接口与重启',title='新记录、原文件和结果重启后保留',detail='接口和重启验证新记录及原始凭证持久化；不执行外部退款、发送或通知。',path='outputs/r1/接口与重启验收.json')])
    for evidence in plan['evidence']:
        if evidence['id'] in {'E01','E02','E03'}:
            evidence['kind']='首批实施前 · '+evidence['kind']
            evidence['detail']='此为实施前快照，用于追溯；新版首批能力见E06—E08。'+evidence['detail']
    plan['decision']='首批5项本地能力已补齐；剩余7项任务缺口及正式接入条件继续保留，真实业务规则待确认。'
    plan['changes']=['保留31项任务；首批F03/F05/F09/F10/F14更新为本地支持。','现状视图包含R0与已实施R1；R2和正式接入条件仍属未来范围。','11条流程中5条在限定本地范围支持、4条部分支持、1条未支持、1条待业务接入。']
    data['roadmap'][1].update(title='首批已补齐',description='客户结果、材料追补/原始凭证、知识回查与缺口治理已有本地流程；真实业务规则继续验证',task_ids=['F05','F09','F03','F14','F10'])
    data['version']='2026-10-26-v3-r1'
    return data
