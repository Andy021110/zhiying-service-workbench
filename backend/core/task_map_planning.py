"""Evidence-backed planning layer; future acceptance criteria are not test results."""
from copy import deepcopy


def criterion(given, when, then):
    return dict(given=given, when=when, then=then)


def story(id, activity, release, title, tasks, benefit, criteria, evidence, dependencies=()):
    return dict(id=id, activity_id=activity, release_id=release, title=title,
                task_ids=tasks, benefit=benefit, acceptance=criteria,
                evidence_ids=evidence, depends_on=list(dependencies),
                implementation='local' if release=='R0' else 'planned',
                acceptance_state='本地回归证据可查' if release=='R0' else '目标验收条件，尚未实现或验收')


STORIES = [
    story('B01','A01','R0','安排本班责任与处理顺序',['T01','T12'],'主管和客服能够找到下一件应处理的事',[
        criterion('当前成员已进入个人或共享范围','筛选无人认领、到期和逾期','能进入同一原工单；跨空间成员不能被分派')],['E01','E02']),
    story('B02','A02','R0','保留原话并核对受理事实',['T02','T03','T04'],'回复可以区分客户原话、订单事实和机器翻译',[
        criterion('同一空间已有该评价事项','再次受理同一评价','打开原事项而非再建一单'),
        criterion('订单日期缺失或翻译失败','核对时效或重试','明确缺失信息或失败；不推测赔付政策')],['E01','E02','E04']),
    story('B03','A03','R0','形成、修订并交付本地回复稿',['T05','T07','F06'],'模型不可用时也能完成本地回复准备',[
        criterion('模型失败或响应丢失','重试同次请求或保存人工稿','保留原话、不重复保存，人工稿可采用与导出'),
        criterion('政策引用已经失效','尝试采用旧草稿','要求重新核对依据，旧采用稿的历史仍保留')],['E01','E04']),
    story('B04','A03','R0','切换事项后恢复未提交内容',['T06'],'多事项处理时不丢编辑内容',[
        criterion('当前浏览器有未提交草稿','切换或刷新；同时服务端已存在新版','保留本地文字并提示核对，不静默覆盖新版')],['E01','E04']),
    story('B05','A04','R0','交接有接受、退回与持续责任',['T08','T09','T13','F07'],'接班之前仍有人负责跟进',[
        criterion('甲发起交接给乙','乙尚未接受或说明原因退回','甲继续负责；期限、下一步与历史保留'),
        criterion('非候选成员或过期版本','尝试确认交接','操作被拒绝；候选人按当前版本接受后才切换责任人')],['E01','E02','E04']),
    story('B06','A05','R0','记录内部结案并保留重开历史',['T10','T11'],'已处理和继续跟进都有明确记录',[
        criterion('仍有关联未完成工单或待接受交接','尝试直接结案','阻止跳过未完成工作'),
        criterion('事项已经结案','填写原因重开','恢复原事项并保留上次结果和重开记录')],['E01','E02']),
    story('B07','A06','R0','维护缺口与审核生效知识',['T15','T16','T17'],'回复使用可核对的有效业务依据',[
        criterion('缺口拟关联测试、待审或归档文档','尝试标记已补齐','拒绝作为生效业务依据'),
        criterion('已有生效版且新版待审','继续业务检索','保留原生效版直到新版通过审核')],['E01','E02']),
    story('B08','A06','R0','从累计指标回到原事项',['T14'],'主管能核对积压和本地结果',[
        criterion('范围内有本地工单和事项','查看服务概况并点击指标','进入相应记录；草稿采用量不计作客户解决率')],['E01','E02']),
    story('N01','A05','R1','分别登记内部完成与客户结果',['F05'],'客服交班时能知道客户是否认可及下一步',[
        criterion('内部执行已完成但客户未回复','登记客户结果','可选择待确认、确认解决、不认可或无法联系；不自动推断已解决'),
        criterion('客服人工记录客户反馈','保存或更正结果','记录反馈发生时间、录入人、说明与人工来源；更正保留历史'),
        criterion('客户不认可或仍待跟进','决定是否结案','按业务确认的退出规则要求负责人和下一步；无法联系不计入客户确认解决'),
        criterion('没有真实渠道回执','查看人工登记结果','明确人工登记，不生成已送达或客户已读状态')],['E03','E05'],['B06']),
    story('N02','A02','R1','逐项追补并核验所需材料',['F09'],'同事接手后能直接看到缺什么',[
        criterion('缺件事项材料不足','创建追补清单','每项有名称、必要性、负责人、期限及待收集/已收到/已核验状态'),
        criterion('材料已经收到但未核验','切换接班成员','保留收集状态和来源，不把已收到自动当作审核通过'),
        criterion('清单尚有必要材料缺失','推进处理方案','明确缺项和下一步，允许带原因记录例外而非静默跳过')],['E02','E03','E05'],['B02','B05']),
    story('N03','A02','R1','保存并查看属于当前事项的凭证',['F03'],'授权同事能核对原始材料',[
        criterion('已选定事项和清单项','上传允许类型与大小的文件','附件绑定事项、上传人、时间和原始来源，可查看原文件'),
        criterion('非本事项可见范围的用户','尝试访问附件','拒绝访问；不能只隐藏前端链接'),
        criterion('文件过大、类型不允许或上传中断','提交或重试','清楚说明原因，不产生假成功或无法访问的清单项'),
        criterion('附件需移除或材料保留期到期','按确定的保留规则处理','有操作原因和历史；不擅自确定业务保留期')],['E03','E05'],['N02']),
    story('N04','A06','R1','知识生效后逐项回查相关事项',['F14'],'补齐规则能推动原事项继续处理',[
        criterion('业务文档审核生效并关联缺口','查看影响范围','列出通过缺口/引用明确关联的事项；注明范围，不声称穷尽语义相关事项'),
        criterion('相关事项需要重新核对','负责人处理回查任务','记录待回查/已回查/不适用、说明、处理人和依据版本'),
        criterion('多人同时回查或文档再次变更','提交回查结果','检查版本；保留历史，不自动改写已采用回复或重开已结案事项')],['E02','E03','E05'],['B07','B05']),
    story('N05','A06','R1','更正、撤销或合并知识缺口',['F10'],'知识维护队列保留有效工作',[
        criterion('问题描述错误或重复','编辑原题、撤销或选择合并目标','要求原因，保留原文和来源事项关系'),
        criterion('合并目标不存在、越权或形成循环','确认合并','拒绝操作；正常合并可从原记录找到目标'),
        criterion('缺口被撤销或合并','查看客户事项','不自动结案；继续保留客户跟进安排')],['E02','E03','E05'],['B07']),
    story('N06','A02','R2','合并重复事项并撤销误建',['F08'],'避免同一问题被重复推进',[
        criterion('人工发现同一范围内重复事项','选择主事项并说明原因','保留原话、工单、来源和转向关系，不重复计算当前待办'),
        criterion('跨空间、自己合并自己或已合并目标成环','提交合并','拒绝操作；撤销误建也需保留审计')],['E01','E03','E05'],['B02']),
    story('N07','A02','R2','按可靠客户标识查看历史问题',['F04'],'客户再次联系时减少重复询问',[
        criterion('已有经过确认的稳定客户标识','查看历史事项','仅展示权限范围内可确认属于同一客户的记录'),
        criterion('只有匿名评价或相似名字','尝试关联客户','不自动认定为同一人；允许按订单或原事项人工查找')],['E03','E05'],['B02']),
    story('N08','A04','R2','按服务时段计算承诺并发现升级事项',['F11'],'主管能解释期限和超时原因',[
        criterion('已有业务认可的承诺模板、工作时段和例外','安排期限','展示采用规则和计算结果；手动改期保留原因'),
        criterion('事项进入等待、临近到期或超时','计算剩余时间与升级','按明确暂停规则处理，主管可查升级原因；是否通知另行配置')],['E02','E03','E05'],['B05']),
    story('N09','A06','R2','按周期核对效率与重复问题',['F13'],'主管能根据可解释的数据决定改进',[
        criterion('选择明确周期和工作范围','查看处理时长与原因分布','显示时间口径、样本数及缺失数，可回查原事项'),
        criterion('存在重开、等待与人工客户结果','计算指标','区分首次响应、内部完成、客户确认；无样本显示暂无数据')],['E02','E03','E05'],['N01','B08']),
    story('P01','A03','RG','发送真实消息并核对回执',['F01'],'能够核实对客消息的执行结果',[
        criterion('渠道与收件人已授权','正式发送或网络失败重试','幂等发送并保存真实平台回执；失败有可恢复状态')],['E03','E05'],['P03','B03']),
    story('P02','A04','RG','执行退款或补发并核对平台结果',['F02'],'处理方案可以对应实际订单结果',[
        criterion('平台权限、规则与审批均满足','执行或重试','记录外部操作标识和最终结果；不重复退款/补发，失败后明确责任人')],['E03','E05'],['P03','B05']),
    story('P03','A01','RG','使用可信身份与组织授权',['F12'],'正式多人服务时有可信的权限边界',[
        criterion('员工加入、调岗或离职','访问事项、知识与附件','按组织授权限制访问并记录审计；本地标识不作为企业登录')],['E03','E05']),
]


def check(id, text, result, evidence):
    return dict(id=id, text=text, result=result, evidence_ids=evidence)


FLOWS = [
    dict(id='C01',title='物流晚到：从受理到客户结果',scenario_ids=['S01'],scope='包含对客发送与客户结果登记',status='partial',task_ids=['T02','T03','T04','T05','T07','F01','T09','F05','T10'],checks=[
        check('C01a','原文、订单日期与回复依据可核对','covered',['E01','E04']),check('C01b','真实发送、送达或失败回执','external',['E03']),check('C01c','客户认可、不认可或待确认分别记录','missing',['E03'])],gap='回复准备和本地跟进已有；发送回执与客户结果仍会中断完整闭环',next_story_ids=['N01','P01']),
    dict(id='C02',title='缺件/质量：补齐材料再制定方案',scenario_ids=['S02'],scope='材料清单、原文件与人工核验，不包含真实补发执行',status='partial',task_ids=['T02','F09','F03','T03','T05'],checks=[
        check('C02a','记录商品、数量、诉求与材料说明','covered',['E01','E02']),check('C02b','逐项追补、已收到与已核验分别记录','missing',['E03']),check('C02c','保存凭证原文件并按事项权限访问','missing',['E03'])],gap='目前只能写材料说明，接班后仍需阅读备注整理缺项',next_story_ids=['N02','N03']),
    dict(id='C03',title='交接班：接受或退回并继续负责',scenario_ids=['S03'],scope='本地成员人工交接；自动升级与企业账号属于其他流程',status='covered',task_ids=['T09','T13','T08','F07'],checks=[
        check('C03a','接受前原责任人持续负责，退回需要原因','covered',['E01','E04']),check('C03b','候选人、版本与待交接结案限制','covered',['E01']),check('C03c','待我接手、等待接手和退回队列可查','covered',['E02','E04'])],gap='当前范围本地支持；真实班次节奏和可用性仍需业务观察',next_story_ids=['N08']),
    dict(id='C04',title='缺少规则：维护生效后回到原事项',scenario_ids=['S04'],scope='包含缺口治理和明确关联事项逐项回查',status='partial',task_ids=['T15','F10','T16','T17','F14','T05'],checks=[
        check('C04a','缺口登记、分派、生效文档校验','covered',['E01','E02']),check('C04b','更正、撤销或合并误登记缺口','missing',['E03']),check('C04c','影响事项清单与逐项回查状态','missing',['E03'])],gap='能打开原事项；文档生效后缺少独立回查清单和逐项确认',next_story_ids=['N04','N05']),
    dict(id='C05',title='生成中断：恢复或手写继续回复',scenario_ids=['S05'],scope='本地回复准备和当前浏览器编辑恢复；不含真实消息重发',status='covered',task_ids=['F06','T06','T05','T07'],checks=[
        check('C05a','网络未达服务端时输入可恢复','covered',['E04']),check('C05b','响应丢失或重试不重复原话与回复','covered',['E01','E04']),check('C05c','无需模型保存人工稿、采用、复制与导出','covered',['E01','E04'])],gap='本地流程已有；历史浏览器故障模拟证据与本轮后端回归分开标记',next_story_ids=[]),
    dict(id='C06',title='内部完成之后确认客户结果',scenario_ids=['S01','S02'],scope='人工登记反馈及来源，不要求先连接渠道',status='missing',task_ids=['F05','T10','T11'],checks=[
        check('C06a','内部完成与客户结果使用独立字段','missing',['E03']),check('C06b','人工来源、反馈时间、更正历史与下一步','missing',['E03']),check('C06c','无法联系不计入客户确认解决','missing',['E03'])],gap='只有本地解决结果文本；客户结果分类、来源与确认历史尚未实现',next_story_ids=['N01']),
    dict(id='C07',title='重复与误建：保留记录后合并/撤销',scenario_ids=['S05'],scope='评价受理去重以及人工、跨来源重复治理',status='partial',task_ids=['T02','F08'],checks=[
        check('C07a','同一空间同一评价受理去重','covered',['E01']),check('C07b','已有人工重复事项合并与误建撤销','missing',['E03'])],gap='自动防重复受理已有；已产生的重复事项没有治理入口',next_story_ids=['N06']),
    dict(id='C08',title='服务承诺：计算期限与超时升级',scenario_ids=['S03'],scope='含工作时段、等待暂停规则与升级责任',status='partial',task_ids=['T09','F11','T13'],checks=[
        check('C08a','手工期限、下一步、到期和逾期队列','covered',['E01','E02']),check('C08b','承诺模板、工作日计算、暂停和升级','missing',['E03'])],gap='能看到手填期限是否超时；统一业务承诺规则尚未配置',next_story_ids=['N08']),
    dict(id='C09',title='周期复盘：效率与原因趋势',scenario_ids=[],scope='按周期核对业务耗时、原因与样本数',status='partial',task_ids=['T14','F13'],checks=[
        check('C09a','累计本地数量、积压、重开和原事项回查','covered',['E01','E02']),check('C09b','周期、处理时长、原因趋势与缺失样本','missing',['E03'])],gap='当前累计统计不能回答本周是否比上周更快及具体原因',next_story_ids=['N09']),
    dict(id='C10',title='客户再次联系时找到历史事项',scenario_ids=['S05'],scope='按可靠客户标识跨事项查找；原工单重开另已有支持',status='missing',task_ids=['F04','T11'],checks=[
        check('C10a','按稳定客户标识查看多次联系历史','missing',['E03']),check('C10b','匿名评价不被猜测合并成同一客户','covered',['E03'])],gap='可重开已知原事项；尚无可靠客户身份与跨事项历史入口',next_story_ids=['N07']),
    dict(id='C11',title='正式业务接入与可信授权',scenario_ids=['S01','S02'],scope='真实渠道、退款补发平台以及企业身份系统',status='external',task_ids=['F01','F02','F12'],checks=[
        check('C11a','真实发送回执与订单执行结果','external',['E03']),check('C11b','企业登录、组织授权、离职撤权与知识隔离','external',['E03'])],gap='需要先确认渠道、平台与身份系统及授权范围，再安排接入',next_story_ids=['P01','P02','P03']),
]

TASK_GROUPS = [
    ('G01','A01','明确协作与访问范围',['T12','F12']),
    ('G02','A01','确定本班处理顺序',['T01']),
    ('G03','A02','识别问题并找到关联记录',['T02','F04','F08']),
    ('G04','A02','核实事实与所需材料',['T03','T04','F03','F09']),
    ('G05','A03','准备可核对的答复',['T05','T06','F06']),
    ('G06','A03','交付答复并保存修订',['T07','F01']),
    ('G07','A04','分配、交接并继续跟进',['T08','T09','T13','F07']),
    ('G08','A04','执行方案并管理承诺',['F02','F11']),
    ('G09','A05','核实结果并决定结案',['T10','F05']),
    ('G10','A05','继续处理原问题',['T11']),
    ('G11','A06','维护知识并推动事项回查',['T15','T16','T17','F10','F14']),
    ('G12','A06','根据结果复盘改进',['T14','F13']),
]


def planning_layer(data):
    result=deepcopy(data)
    tasks={t['id']:t for t in result['tasks']}
    # Manual outcome registration has no channel integration dependency.
    tasks['F05'].update(availability='planned',title='登记客户确认、异议或无法联系的结果',
        steps=['选择人工记录的客户结果','填写反馈时间、来源与说明','按业务退出规则安排结案或继续跟进'],
        inputs=['客服核实的客户反馈','反馈发生时间','人工登记来源与说明'],
        depends_on=['T09'],
        output='可区分客户结果与内部结案的记录',
        done='结果类别、来源、反馈时间及更正历史可查；待跟进事项有负责人和下一步',
        acceptance=['客户结果独立于内部结案，包含来源、反馈时间及录入人','更正保留历史；待跟进结果明确负责人和下一步'],
        exception='真实发送回执另属F01；人工登记不生成已读、已送达或满意度结论',
        current_support='可填写本地解决结果文本，尚无独立客户结果分类',
        gap='缺客户结果、人工来源、反馈时间及更正历史；人工登记可先做，真实回执另属F01',
        verification='先确认结案规则；按N01逐条验收人工登记，不生成虚假渠道回执')
    for s in result['scenarios']:
        for d in s['decisions']:
            if s['id']=='S01' and d['at']=='F01':d['no']='保留本地回复准备状态；真实发送待接入，客户结果可先人工登记但尚未实现'
    result['metrics'][0]['status']='本地结案已有；人工客户结果待实现，真实渠道回执待接入'
    for task in result['tasks']:
        related=[s for s in STORIES if task['id'] in s['task_ids']]
        task.update(activity_id='A'+str(task['stage']+1).zfill(2),story_ids=[s['id'] for s in related],
                    evidence_ids=sorted(set(e for s in related for e in s['evidence_ids'])),
                    level='支撑能力' if task['id'] in ['T06','F06','F12'] else '用户任务',
                    research_state='待真实业务观察验证')
    result['version']='2026-10-26-v3-audit'
    result['principle']='角色与目标 → 活动 → 用户任务 → 需求故事 → 版本范围 → 验收与覆盖证据'
    result['planning']=dict(
        updated_at='2026-10-26',owner='产品维护者（业务责任人待指定）',
        purpose='先补需求，再检查覆盖，最后按完整业务流程统一修改。',
        decision='本轮完成地图与覆盖评估；R1/R2为建议版本，尚未实现或承诺排期。',
        scope='本地售后工作台：历史样本、人工处理与本机协作。正式身份、真实发送与订单执行另列接入条件。',
        legend={'covered':'已支持（限定范围）','partial':'部分支持','missing':'尚未支持','external':'待业务接入'},
        workflow=['补全角色、目标和任务','写清正常路径与异常退出','核对界面、接口与测试证据','按完整流程确定版本范围','统一修改后逐条验收'],
        methods=[dict(name='用户故事地图 · 主图',use='按活动展开用户任务和具体需求，用版本范围组织开发；现状与目标可切换。',url='https://www.jpattonassociates.com/wp-content/uploads/2015/03/story_mapping.pdf'),
                 dict(name='用户旅程图 · 研究补充',use='围绕一个角色和场景记录行动、疑问和痛点；用户情绪与原话需要研究依据。',url='https://www.nngroup.com/articles/journey-mapping-101/'),
                 dict(name='服务蓝图 · 协作补充',use='复杂场景再展开客户、前台客服、后台处理和支持系统的交接；本轮不声称已完成服务蓝图。',url='https://www.nngroup.com/articles/service-blueprints-definition/')],
        activities=[dict(id='A'+str(i+1).zfill(2),title=s['name'],outcome=s['output'],task_ids=s['task_ids']) for i,s in enumerate(result['stage_details'])],
        stories=deepcopy(STORIES),flows=deepcopy(FLOWS),
        releases=[dict(id='R0',name='现状基线 · 本地准备与协作',state='本地已有',goal='从受理、事实核对、回复准备到人工交接和内部结案有记录。',exit='限定本地工作范围；客户确认、真实发送和平台执行继续单独列缺口。',inherits=[],story_ids=[s['id'] for s in STORIES if s['release_id']=='R0']),
                  dict(id='R1',name='建议第一轮 · 补齐记录闭环',state='待统一实施',goal='材料有清单，客户结果可人工登记，知识更新能回到相关事项。',exit='在缺件投诉和知识缺口两个场景中，逐条验收N01—N05及既有流程回归。真实渠道执行另行接入。',inherits=['R0'],story_ids=[s['id'] for s in STORIES if s['release_id']=='R1']),
                  dict(id='R2',name='建议后续 · 队列治理与效率',state='待验证',goal='减少重复事项和重复核对，并解释服务承诺与周期效率。',exit='先确认可靠客户标识、工作时间和指标口径；按对应场景整体验收。',inherits=['R0','R1'],story_ids=[s['id'] for s in STORIES if s['release_id']=='R2']),
                  dict(id='RG',name='正式使用前 · 接入条件',state='依赖外部系统',goal='确定真实渠道、平台执行与可信身份授权边界。',exit='有明确业务系统、接口权限与责任人后，再确定接入次序；不是紧接R2的承诺排期。',inherits=['R0'],story_ids=[s['id'] for s in STORIES if s['release_id']=='RG'])],
        evidence=[dict(id='E01',kind='本轮后端回归',title='隔离测试库中的功能与权限回归',detail='后端测试覆盖受理去重、期限、交接、结案、知识审核、失败恢复与人工稿；结果见随附后端测试记录，不代表真实业务有效性。',path='outputs/taskmap-v3/后端测试.txt'),
                  dict(id='E02',kind='本轮浏览器与接口核对',title='只读检查当前业务入口和字段',detail='查看已存在验收样本、待办、知识与统计入口；检查API模型。该证据说明现有入口和字段，不等同于本轮重新执行所有业务分支。',path='outputs/taskmap-v3/产品覆盖检查.json'),
                  dict(id='E03',kind='本轮实现核查',title='前端操作与后端请求模型核对',detail='核对TicketPatch/ConversationPatch/IntakeInput/GapEdit、operations队列/报告及App/KnowledgeGapPanel；未实现项不能凭已有备注或相似按钮判作支持。',path='outputs/taskmap-v3/实现核查.json'),
                  dict(id='E04',kind='历史浏览器演练',title='上一轮失败恢复与双成员交接',detail='2026-10-25：17项浏览器检查及12项接口/重启检查；保留原日期，故障由自动化模拟。',path='outputs/fixes/浏览器验收.json'),
                  dict(id='E05',kind='需求假设',title='用户提出的方向与业务推演',detail='场景价值、频率和退出规则尚未经过真实客服访谈或生产观察。目标验收条件不代表功能已通过测试。',path='')],
        metrics=[dict(name='材料反复追补次数',definition='每个事项明确发起的追补轮次；不以备注条数代替',baseline='待采集',target='业务试用后确定',story_ids=['N02','N03']),
                 dict(name='客户结果完整性',definition='有客户结果类别、反馈时间、来源及录入人；无法联系与确认解决分开',baseline='无独立字段，待实现后采集',target='业务试用后确定',story_ids=['N01']),
                 dict(name='知识回查完成情况',definition='按明确关联事项计算待回查、已回查、不适用，并记录版本',baseline='待采集',target='业务试用后确定',story_ids=['N04']),
                 dict(name='交接等待时间',definition='从发起交接至接受/退回；进行中事项单列，不与处理耗时混用',baseline='已有时间记录，尚未汇总',target='业务试用后确定',story_ids=['B05','N09'])],
        research_queue=[dict(question='什么情况可以内部结案？客户不回复多久、经过几次联系后如何退出？',decision='N01结果分类及退出规则',owner='客服主管（待指定）'),
                        dict(question='缺件/质量问题分别要求哪些材料，谁能豁免？附件如何保留？',decision='N02/N03清单模板、访问与保留规则',owner='售后负责人（待指定）'),
                        dict(question='规则生效后哪些事项必须回查？已结案事项是否需要重新联系？',decision='N04影响范围与回查责任',owner='知识维护与客服主管（待指定）'),
                        dict(question='以什么标识确认同一客户？渠道和身份系统是哪一个？',decision='N07与RG接入边界',owner='业务系统负责人（待指定）')],
        changes=['保留31个任务和原T编号；补充活动、20条需求故事及版本范围。','F05改为可先实现的人工登记需求，真实渠道回执保留在F01。','11条流程按限定范围评估，覆盖状态与研究验证状态分别记录。','本轮完成地图和覆盖检查，业务功能仍以当前产品实际能力为准。'])
    result['planning']['task_groups']=[dict(id=id,activity_id=activity,title=title,task_ids=ids) for id,activity,title,ids in TASK_GROUPS]
    for group in result['planning']['task_groups']:
        group['story_ids']=[s['id'] for s in result['planning']['stories'] if set(group['task_ids'])&set(s['task_ids'])]
        for id in group['task_ids']:tasks[id]['group_id']=group['id']
    for s in result['planning']['stories']:
        s['role_ids']=sorted({tasks[id]['role'] for id in s['task_ids']})
        s['group_ids']=[g['id'] for g in result['planning']['task_groups'] if set(g['task_ids'])&set(s['task_ids'])]
    return result
