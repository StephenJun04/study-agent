# Progress and verification

2026-10-26：本地及私有远端均为空仓库；原开发提示词已找到并读取，其推送授权被当前本地限制取代。两份 PDF、五个 ZIP 已静态审计。详细 rubric 缺失。用户缩小即时目标为 demo，选择 DeepSeek，尚未配置 key。使用专用 PostgreSQL 端口 55432，既有 COMP7104 数据库保持原状。

## 2026-10-27：demo 交付核对

以下置信水平为高（记录的程序行为），真实教学质量为未知。

| 检查类别 | 实际结果与证据 |
|---|---|
| 静态检查 | `.venv/bin/ruff check studyagent tests scripts`、`node --check studyagent/static/app.js` 通过。原生前端无需 npm 构建。 |
| 确定性 / fake / 模拟 HTTP | `python scripts/evaluate.py`：50 passed、0 failed、0 skipped；见 `evaluation/results/summary.json`、`pytest.xml`。数据库集成测试使用真实 PostgreSQL。八类场景的契约检查通过，不是八类场景的真实语义评估。 |
| 干净环境 | 新源码副本、新 Python 3.12.14 venv、新数据库：71 个锁定包一致，`pip check`、两次迁移、启动、12 项 HTTP 检查通过；副本中再运行 50 项测试通过。见 `clean-room.json`。临时服务已停止。 |
| 真实重启 | 终止并重新启动本项目 uvicorn，等待中的 session/thread/quiz/step 均一致；见 `restart-process.json`。 |
| 浏览器操作 | 实际上传原创样例、带引用对话与追问、开始学习、答错切 example 和新题、再答对、刷新/继续、停止。停止后无活动题；可回到普通对话。见 `demo-ui.png`、`browser-check.json`。 |
| 并发与恢复修复 | 同概念的跨会话掌握更新加事务锁；完成请求重试幂等；quiz 落库而 checkpoint 未提交的恢复重放安全；教学引用只取最终模型输入中实际保留的证据。回归测试在 `test_api_flow.py`。 |
| 真实 embedding | Ollama `nomic-embed-text` 单次本地调用返回 768 维有限非零向量，观察耗时 2471.29 ms；见 `embedding-probe.json`。一次观察不是性能保证。 |
| 真实 DeepSeek | 未运行：本地尚未配置 key。缺 key 时预检退出 2；不会静默转 fake。真实认证、材料审核、图抽取、回答/出题/判分质量均未知。 |
| 人工复核 / baseline | 未运行。基础 RAG 路径已实现；没有真实对照准确率、引用支持率或长期学习收益结论。 |

浏览器测量宽度为 624 px，scrollWidth 也是 624 px；该窄屏观察未发现横向溢出。浏览器错误/警告日志查询为空。键盘 Home 可在功能标签间导航；未完成全部屏幕阅读器或设备兼容性审计。

## 故障与非功能边界

- 外部请求：模拟超时、429、503、认证失败和坏 JSON；有限重试/一次格式修复，耗尽则返回明确错误。重试可能重复供应商请求或计费，不能宣称外部 exactly-once；学习状态写入另用唯一约束、事务和锁保证幂等。
- 状态故障：重复/过期/并发作答、评分后检查点重放、quiz 提交间隙和真实进程重启均有证据。停止状态拒绝恢复和后续工具调用。
- 目标：最终输入不超过配置预算（默认 7000 估算 token），停止后新增模型调用数为 0，一次有效作答只加一次次数，空间外对象访问被拒绝；相关测试通过。token 用 UTF-8 字节数/3 估算，有供应商 usage 时另记录实际值。没有实测缓存命中。
- 模型超时默认 90 秒且重试有界；这不是端到端响应时延目标。真实生成时延、并发负载、最低硬件配置未测。演示为本机单用户，不提供公网多用户认证。
- 资料清单共 10 份，默认下载 2 份公开 PDF（Transformer / RAG）已验证可解析和 SHA-256。没有完成全数据集标注与实验。网络补充限定 arXiv，扫描 PDF 没有 OCR。

源码快照使用逐文件 SHA-256 版本清单，不创建 Git commit。包中排除 `.env`、上传、数据库、课堂原件与答案；最终 ZIP 解包核验单独写入 `output/package-check.json`，不循环写回 ZIP。
