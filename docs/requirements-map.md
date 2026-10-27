# 演示范围与实现对应

本表用于检查本机 demo 是否覆盖 proposal 的主要交互。代码路径与测试名称可查证；测试是否通过须以本次 `scripts/evaluate.py` 生成的结果为准，不把静态实现说明当作运行结果。

| 需求 | 当前实现/检查入口 | 验证边界 |
|---|---|---|
| 独立可运行应用、单一学习编排 | `studyagent/main.py`、`learning.py`、静态网页；README 启动命令 | 本地单用户演示，无云部署 |
| Course / 单材料 Focus / 无范围先澄清 | 空间与资料 API；`test_cross_space_objects_and_chat_scope`、`test_focus_admission_keeps_shared_document_and_independent_mastery` | Focus 纳入 Course 重新校验，掌握状态独立 |
| 解析→验证→分块→嵌入→索引，保留来源 | `knowledge.py`；`test_ingestion_preserves_page_sources_and_unknown_mastery`、`test_pdf_actual_page_numbers` | PDF/TXT/MD；扫描 PDF 需另做 OCR；提取文本、上传大小有限制 |
| 不合适、重复、冲突材料不入有效检索 | `test_bad_files_duplicates_and_conflicts_never_enter_retrieval` | 流程可确定性检验，真实材料语义审核质量尚未测量 |
| 引用实际召回资料，缺口不补造 | `test_retrieval_diversity_and_citations_use_actual_sources`、`test_unsupported_answer_claims_are_withheld` | 自动检查引用 ID/逐字片段；语义支持还需人工复核 |
| 缺证据时补充检索并验证 | `Knowledge._search`；`test_web_evidence_is_verified_temporary_and_uses_fixed_hosts`、`test_web_timeout_is_bounded_and_reported` | 限定 arXiv；网页为临时证据，不自动写成课程资料/记忆 |
| 有证据的概念图和前置关系 | `knowledge.py`；`test_cycle_and_unsupported_edges_are_pending` | 未知或循环边保持 pending，不称为已证实先修关系 |
| 三种教学模式、真实输入后更新 | `learning.py`；`test_full_loop_persistent_resume_idempotent_stop`、`test_prerequisite_then_repeated_success_advances` | mastery 为启发式；fake 无真实教学效果结论 |
| 会话可恢复，提交幂等，明确停止 | PostgreSQL/LangGraph checkpoint；`test_checkpoint_replay_after_grade_commit_is_idempotent`、`test_concurrent_submission_cannot_double_update` | 所有模式均使用真实数据库；无自动模拟学生作答 |
| 记忆有归属、可修订、有失效历史 | `test_preference_revision_scope_and_failure_recovery` | 偏好来自显式用户输入；空间隔离，不推断个人事实 |
| 上下文压缩保留纠正和状态，记录最终输入 | `context.py`、`providers.py`；`test_context_retains_corrections_and_current_state_under_budget`、`test_final_input_budget_includes_schema_task_payload_and_context` | token 预算含任务/模式/资料；估算方法有标记，未声称缓存命中 |
| 模型错误和网络故障有界恢复 | `test_bad_json_is_repaired_once_with_safe_validation_error`、`test_timeout_is_bounded_and_never_falls_back_to_fake` | 模拟 HTTP 测试不等于真实服务可靠性测量 |
| 固定八类场景、回答与行动分开 | `evaluation/scenarios.json`、`scripts/evaluate.py` | 目前仅流程/契约结果，真实准确率与学习增益未测 |
| 公平的基础 RAG 对照 | `/api/chat` 的 `baseline=true`，相同检索/模型/回答路径 | 省略 mastery/preferences，只比回答/引用；真实比较 `not_run` |
| 来源可追溯、语料公开 | `data/sources.json`、`scripts/fetch_materials.py` | 清单 10 份；默认只下载 2 份 demo；下载不等于完成实验 |

完整 8–12 份材料的人工概念/定义/前置/问题/参考答案标注、真实模型重复评估、详细性能测量、最终报告 PDF 与正式提交包均不在本次 demo 完成声明内。评测参考答案不得进入检索或教学 prompt。

组号：____　成员实际贡献：____　人工复核记录：____
