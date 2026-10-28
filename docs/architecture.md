# 架构与关键边界

[可交互架构图：完整总览、机制切换与固定源码](http://47.76.25.13/portfolio/zhiying.html#interactive-architecture)

## 请求怎样走过系统

1. Vue 将客户原话、客服操作、手写回复与内部备注区分提交。
2. FastAPI 校验事项范围与版本，业务记录落到 SQLite；不会因为模型返回一段话就完成工单。
3. 明确的订单事实查询直接读取只读数据。翻译与政策答复使用各自链路，不把缓存命中计算为模型调用。
4. 需要准备答复时，先判断当前问题和知识可用性。业务模式只接受适用的生效版本；缺少依据就列缺口。
5. Agent 编排按领域分发；复合问题允许技术与账单分别执行。当前恢复状态应覆盖旧故障关键词，复发时重新识别。
6. 草稿返回后仍要核对内容与来源。采用、审批、内部结果与客户结果独立持久化。

## 存储职责

| 存储 | 主要职责 | 边界 |
| --- | --- | --- |
| SQLite | 会话消息、事项、工单、材料、审批、知识元数据、执行记录 | 业务事实来源；不是从记忆模型反向推断状态 |
| Redis | 工作记忆与会话上下文 | 不能替代事务记录，重启后计数口径单独说明 |
| ChromaDB | 知识检索、用户画像与情景记忆 | 检索命中还要经过版本、审核与范围筛选 |
| 浏览器存储 | 当前浏览器的未提交草稿与显示偏好 | 不是跨设备同步或服务端成功提交的证据 |

## 源码入口

- `backend/api/main.py`：服务生命周期与生成入口。
- `backend/api/*_routes.py`：受理、工单、交接、材料、示例与运营接口。
- `backend/core/workbench.py`：SQLite 记录、消息、版本与采用流程。
- `backend/core/operations.py`、`service_followup.py`、`handoff_tasks.py`：业务办理与后续责任。
- `backend/core/knowledge_policy.py`：知识适用与生效规则。
- `backend/core/fact_answers.py`：明确事实问题的直接处理。
- `backend/core/conversation_context.py`、`intent_recognizer.py`：当前问题与历史上下文。
- `backend/agents/agent_orchestrator.py`：通用、技术、账单 Agent 编排。
- `backend/core/execution_calls.py`：跨重启保留的助手执行记录。
- `backend/mcp/tool_manager.py`、`knowledge_base.py`：内部工具管理与检索。
- `backend/core/task_map*.py`：任务、场景、规划与验收关联。

## 状态设计

`生成草稿 → 客服核对 / 修订 → 本地采用` 是答复准备流程，不是对外发送链路。

`交接发起 → 接受 / 退回 → 继续跟进` 要保留材料清单及版本。冲突时明确拒绝覆盖，用户决定下一步。

`内部完成 → 本轮客户结果 → 结案` 不能跳过仍待处理的工作。再次提出问题时重开原事项，历史确认不抹除，也不替代新轮次确认。

## 当前不能外推的能力

本地成员切换不是企业认证；SQLite 本地流程不是生产高并发证明；内部模块叫 MCP 不等于外部协议互通；执行成功率不等于回答正确率。对外发送、资金与订单写操作尚未接入。


[Archify 完整交互架构](http://47.76.25.13/portfolio/architecture/zhiying-archify.html)：节点来源固定到已检查 Git 提交，可追踪关系并下载离线 HTML；这是一张架构快照。


## 完整交互架构与分层阅读

[作品集内直接查看](http://47.76.25.13/portfolio/zhiying.html#interactive-architecture)，无需展开。当前提供 系统总览、Agent 与知识、工单与知识治理 三张图。它们依据固定提交里的真实调用、校验和持久化职责编制；一个逻辑组件不等于一个独立进程或微服务。旧版只展示答复或查询主路径，现已扩展为完整系统和关键机制图。

新版工作台从 SQLite 事项和消息构建上下文；Redis 工作记忆、Chroma 情景记忆与画像是兼容 CLI 的独立链路。图中不把兼容链路虚构为工作台每次请求的必经步骤。内部知识工具模块也不等于已经接入外部 MCP 平台。
