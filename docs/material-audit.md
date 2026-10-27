# 材料审计

核对日期：2026-10-26（香港）。置信水平：高（对下列实际文件的静态内容）；功能是否实现须以代码和本次测试为证。

## 输入与边界

两份 PDF 均可读取；proposal 共 4 页，课程指南共 2 页。五个 ZIP 均已先列目录，再以 `zipfile` 静态读取正文、notebook 的 markdown/code cells；未执行归档内代码、初始化、安装或清库脚本。未将 notebook 历史输出、`setup_report.json`、logs 或 pyc 当作当前测试证据。ZIP 路径检查未发现绝对路径、`..` 穿越或符号链接。系统文件、`__MACOSX`、`.DS_Store` 和编译缓存不作为材料。

材料优先级：本次用户指令与适用控制规则 > 课程指南（交付要求）> 本次上传 proposal（项目承诺）> 练习（方法参考）；开发提示词仅提供工程偏好。练习中的“完成某题”“只编辑学生文件”“Reset demo”等不是本项目操作指令。

| 实际输入 | SHA-256 |
|---|---|
| `COMP7608_Project_Proposal(2)(1).pdf` | `b97be113082df18607da17be101cfcc4d076efd447e3b9b683ccd2c4ae504041` |
| `COMP7608B_Final_Project_Student_Guideline.pdf` | `1c25a60d52583c80bfe91bc02fbfc0b46c4c24ec495f41dc526856d151c47b97` |
| `COMP7608B_Hands-on_1.zip` | `9f646085745a4bc3460f8bbec602b1e031a82e2d7db958e5f5b359da73385541` |
| `practice_1_example.zip` | `eb78bab7f90b3265cc1c4afd4bc6beecbecc1aaf56837cc17e788fffd096ff8c` |
| `SSA_Student.zip` | `b1e99f02ab38cf3d85ae52c004e8773dccd49cdbff0634d29ca4c3a27ac26c4c` |
| `SSA_example.zip` | `60404f6ded86b0cccc2e60b9918ac8fb6367bd18943713063475093b33db31b9` |
| `L06_Practice (1).zip` | `6c05d95d06a97966a7e469e3f61c81e3aef0d233bd386b045905254c6868c35c` |

原附件及课堂答案不进入发布包。学号存在于 proposal p1，但不复制到本审计、README 或报告；成员姓名按指南保留。

## Proposal 的实际承诺

标题：**StudyAgent: An Agentic AI Assistant for Adaptive and Reliable Learning**。proposal p1 §1 中成员姓名为 **Lai Man Chit、Yan Wen Jun、Guo Jia Hao、Chen Ming Han**；未见组号，未给出成员实际分工。

| 位置 | 承诺及对实现/评估的约束 |
|---|---|
| p1 §2；p2 §4.1 | 单个 Orchestrator Agent + Tools + State/Memory；General Study Chat、单材料 Focus、共享多材料 Course。General Chat 可澄清或直接结束。Focus 接纳到 Course 后保留范围。结构化动作包含动作、空间、概念、证据 ID，并由应用校验。 |
| p2 §3、§4.2；p3 §4.2 | 上传→解析→验证→分块→embedding→向量存储；保留文档与页/章节来源。材料、检索、记忆验证是不同对象。不可用、不相关、重复、冲突或不确定材料不进入正式知识；冲突保留来源。局部证据不足时查网且网页须先验证；未补齐则澄清/说明缺口。来源优先级不是正确性保证。 |
| p3 §4.3 | JSON 概念图与证据，缺依据/循环边待复核；Concept Explanation、Example/Analogy、Quiz 三模式。根据前置、作答和历史切换。启发式 mastery、次数、错误历史；未测 unknown，不宣称真实能力估计。 |
| p3 §4.4 | 稳定指令/输出契约/工具定义前缀，动态状态和近期完整历史，压缩旧对话且保留原始记录；保护空间、目标概念、未解决问题、明确纠正；逐次记录最终输入长度。仅说明具备 prefix reuse 条件，未实测不能宣称 KV cache 命中。 |
| p3 §4.5 | 观察检索→验证教学→等待真实输入→评估更新→重新规划。支持推进、练习、换解释、再检索、停止；用户请求、完成、重复失败、步数上限均可终止。 |
| p3 §5 | **总计 8–12 份**公开 ML/LLM 文档；相关材料组成一个 Course，其中 **2–3 份**单独形成 Focus。每份记录来源；概念、定义、前置、固定问题与参考答案需人工标注。第二学科有可比语料才考虑。参考答案和预期动作不进入索引或 prompt。 |
| p4 §5 | 运行前固定八类：缺前置、讲解后答错、重复成功、空间外、多文档、不足证据、不合适材料、上下文压缩。回答质量与行动质量分开；基础 RAG 只比较共同的回答和引用能力。验证排除、上下文事实保留、每回合 prompt 长度、成功失败与局限均需记录。评估限于原型流程，不证明长期学习收益。 |

proposal p3 §4.5 将多 Agent、Neo4j、BKT、复杂记忆、额外教学专家等列为可选；本次用户明确排除这些扩张，采用最小单体。实际 proposal 没有规定 LangGraph、FastAPI、PostgreSQL 等具体框架；这些是本次用户明确要求的工程选择。

## 课程指南的交付要求

- p1：提交截止 **2026-11-25 23:59，香港 UTC+8**；演示日 **2026-12-01 或 2026-12-08** 的常规课时，分组安排在提交截止后公布，当前未知本组日期。
- p1：成绩权重 proposal **20%**、最终报告与代码 **50%**、presentation/demo **30%**。指南引用已公布的 final report/code rubric，但输入没有该详细 rubric；不能推断分项评分细则。
- p1：必须是完整、可操作、会决策/用工具/响应观察并停止或澄清的 Agent。组件实验或单纯 benchmark 不够；研究创新、多 Agent 非必需；微调、RLHF、多模态按相关性评价。
- p1：报告覆盖用户需求和 proposal 连续性、计划/交付/未完成差异、设计自主决策、模型版本/提示词/工具/数据/状态、至少两类故障与有界恢复、非功能目标和实测、公平评估/可变性/失败、贡献归属与复用。LLM 评分要明确标准和人工检查。
- p2：完整应用必须独立于 notebook；README 给安装/运行/评估命令、依赖版本、模型配置、服务/数据/付费/硬件条件；包含普通/改变/失败请求、评估、结果、成功失败轨迹和可核验版本。按 README 测试包；排除凭据，标注 mock 和不可用依赖。
- p2：独立报告 PDF 与源码 ZIP；即使附仓库链接仍须源码快照；README 与报告含组号、标题、成员姓名。AI 工具/模型和帮助范围声明，以及项目相关实际 prompts；不要求全部 AI 回复；去敏并承认缺失历史。
- p2：两分钟 pitch、现场自由输入/追问/改变条件/故障恢复、Q&A；录像不能代替现场。全部成员需出席本组指定演示日。

## 第一组：结构化输出和确定性路由

实际读取 `COMP7608B_Handson_1/01_Simple_Chatbot.ipynb`、`Preparation.ipynb`、`prompt_student.txt`，以及 `practice_1_example/02_Simple_Chatbot_Example.ipynb`、`prompt_completed.txt`。以下 cell 编号为 notebook JSON 中 **0 起始**索引，便于精确复查。

- 主 notebook cell 4–5：模型返回 JSON，服务 intent 为 `order_status/delivery_info/contact_support`；一般聊天为 `{"intent":"chat","reply":...}`。`call_service` 查询 SQLite 或澄清，模型不能虚构数据库内容。没有 PDF 分块、embedding、向量检索、文档证据引用或持久对话。
- **契约冲突**：学生 `prompt_student.txt` 要求“恰好一个 intent”，标签包含 `unsupported`；主 notebook cell 4 的 `OUTPUT_SCHEMA`、cell 5 的 `INTENTS`、cell 6/9 的任务说明采用 `chat` 加非空 `reply`。不能直接复制两套互斥规则；StudyAgent 应以一个严格的 `AgentDecision` 契约贯通 prompt、模型解析、路由与 API。
- 学生 notebook `parse_output`（cell 10）、`make_reply`（cell 14）和 `send_request`（cell 16）均尚为 `NotImplementedError`；不作为已完成功能。示例 notebook cell 10/13/16 展示 parse→validate→dispatch→真实结果。
- **文件名差异**：示例说明 cell 6 写 `prompt_complete.txt`，实际加载 cell 7 和真实归档文件均为 **`prompt_completed.txt`**。
- **清库风险**：两个主 notebook cell 2 每次都 `DELETE FROM orders`、`DELETE FROM info` 再从 `data*.json` 重建演示表。此机制不用于项目迁移，不执行它清除学习资料或历史。
- 示例自带的“16 recorded checks”等输出不是本项目当前检查记录；本次未运行课堂示例，也未推断它们当前通过。

## Lecture 05：上下文、工具契约和观察

读取两个包的 `student/task_a_context.py`、`task_b_tool.py`、`task_c_prompt.txt`，以及 `provided/context.py`、`protocol.py`、`tools.py`、`agent.py`。静态字节比较确认两包这四个 provided 文件（另含 checks/model）相同；学生与示例代码不同。

- `SSA_Student/student/task_a_context.py:29–40` 的实际 `assemble_messages` **返回空列表**。其 docstring 说“starter drops history and puts changing state in system”与实际空实现不同，应以代码为准。
- 示例 `SSA_Instructor/student/task_a_context.py:11–26` 深复制消息，稳定 system→保留角色顺序的历史→完整当前回合→把动态状态附于最后当前消息。此方法可借鉴，不把商城条件复制进学习范围。
- 学生 `task_b_tool.py:17–70` 的说明模糊、`order_id` 未必填、函数抛 `NotImplementedError`、`HANDLERS={}`。示例把定义、参数/结果契约、处理函数、显式注册分离。
- `provided/protocol.py:103–126` 校验 JSON、动作、工具名、参数；`provided/tools.py:99–162` 执行边界再次校验参数并验证结果。不得将模型提议当作已执行工具。
- `provided/agent.py:36–88`：model→validate→dispatch→带 `call_id` 的 observation→下一次模型输入；限制工具次数、格式修复和同参数重复调用。结果失败保留错误，不编造业务事实。
- `provided/context.py:16–31` 的 `Session`/`Turn` 是 RAM 数据类，不能替代 StudyAgent 的数据库/checkpoint。`:74–89` 用普通角色消息包裹标注 observation，不产生无配对的原生 tool 角色。`:196–220` 按整回合裁剪，`characters/4` 明确只是英语估计，`shared_prefix_characters` **不是实测缓存命中**。

## Lecture 06：写入、召回、范围、有效性

读取 `student/write_memory.py`、`recall_memory.py`，以及 `provided/memory.py`、`engine.py`、`prompts.py`、`answers.py` 与 README。

- `write_memory.py:23–30` 只忽略 conversation scope，余下为 **`pass`**；`recall_memory.py:26–30` **恒返回 True**，故未过滤范围或有效性。都是有意留空的教学骨架。
- `provided/memory.py:80–89` 的 basic `remember` 替换同 topic/case，可能丢失经历；`:91–107` 的 `semantic` 修订当前值并保留 superseded 版本；`:109–117` 的 `episodic` 按来源追加、去重。对应项目：可修订教学偏好 + 按次保存测验/错误事件。
- `Record.valid`（`:46–56`）检查 active 和到期时间；过期/替代记录保留审计，但不作为当前有效事实。**失败作答仍是有效历史**，valid 不等于 correct。
- `provided/engine.py:87–97` 对每个存储记录调用 recall；`:99–128` 将 stored 和 selected 分开显示；`:153–199` 先写入/筛选，再构建真实模型消息并保存请求。项目要同样能查本轮实际召回范围，而非仅证明“数据库里有”。
- `provided/prompts.py:18–44` 为有限关键字规则抽取器，不是通用语义记忆。`customer/case/conversation` 只提示设计，StudyAgent 应落实用户/空间/概念/会话实际归属。
- `provided/engine.py:71–80` 原子替换 JSON 状态是课堂持久化演示；本项目仍采用 PostgreSQL 的约束/事务与持久 LangGraph checkpoint。`:137–150` 的 Reset 会清所有演示状态，不执行或复用为默认初始化。
- `provided/answers.py:30–113` 从 selected memory 和当前用户报告构造证据表，再检查模型证据 ID；它不会自动修复错误 recall 范围，也不把助手建议当成已发生的用户经历。

## 待补输入与未验证项

- 详细 final report/code rubric 未提供；组号、真实成员分工、人工标注/复核结论、本组演示日未知，必须用待确认标记。
- `StudyAgent_开发提示词.md` 不在上述七个附件内；主执行者已从本机下载目录的 proposal 文件夹找到并读取。原文中的远端推送许可不适用于本次本地 demo；不复制私人绝对路径。
- 本审计只证明阅读与静态比对，不证明任何服务可用、代码测试通过、语义判断准确或当前模型实验结果。
