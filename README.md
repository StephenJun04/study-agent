# StudyAgent — 本地演示

一个基于课程资料的学习助手：在 Course / Focus 空间上传材料、查看来源、问答，并完成“讲解 → 作答 → 反馈 → 调整教学 → 再测验”的持久学习循环。应用使用 FastAPI、LangGraph、PostgreSQL + pgvector；网页由同一服务提供，无需单独启动前端。

本次交付范围是本机 demo。真实生成服务选择 DeepSeek，密钥须由使用者在本机填写；完整数据集评估和最终报告 PDF 尚未开展。fake 模式只验证流程，不代表真实模型能力。组号：____。成员实际贡献及人工复核留待填写，见 [AI 使用记录](docs/ai-use.md)。

Proposal 列出的成员：Lai Man Chit、Yan Wen Jun、Guo Jia Hao、Chen Ming Han。该名单不代表已确认实际分工。

## 给团队：模块与后续工作

代码职责、完整数据流、当前限制及下一步验收顺序见 [架构与完善路线](docs/architecture-and-roadmap.md)。演示操作见 [中文演示步骤](docs/demo.md)，接口见 [API 契约](docs/api-contract.md)。

## 运行条件

- Python **3.12**，依赖版本固定在 `requirements.lock`。
- Docker Engine / Docker Desktop 和 Compose；数据库绑定 `127.0.0.1:55432`。
- 真实模式另需本机 Ollama 服务及 `nomic-embed-text`，以及可用的 DeepSeek API key、网络和账户余额。DeepSeek 调用可能计费；Ollama 嵌入在本机运行。
- 磁盘需容纳 Python 环境、数据库、Ollama 模型及上传文件；本项目尚未测定最低硬件配置或性能保证。

## 安装与真实模式

在项目根目录运行：

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
if [ ! -f .env ]; then cp .env.example .env; fi
docker compose up -d --wait --wait-timeout 90
python -m studyagent.db
ollama pull nomic-embed-text
python scripts/preflight.py
```

先启动 Docker 和 Ollama；首次数据库启动尚未就绪时，等待健康检查通过后再运行迁移。迁移是增量初始化，不清空已有学习记录。默认 `.env.example` 使用 `STUDYAGENT_PROVIDER=deepseek`、`DEEPSEEK_MODEL=deepseek-flash` 和 768 维嵌入；实际请求模型由 `.env` 决定。

用本地编辑器打开 `.env`，填写 `DEEPSEEK_API_KEY`。不要在聊天、网页表单、截图或源码中填写密钥。已有 `.env` 不应被示例文件覆盖。配置修改后重启应用。

```sh
python scripts/preflight.py
uvicorn studyagent.main:app --host 127.0.0.1 --port 8000
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。默认预检只查询 PostgreSQL 和 Ollama 模型列表，检查密钥是否存在，**不能证明 DeepSeek 身份验证或生成成功**。需要实际验证时显式运行：

```sh
python scripts/preflight.py --probe-real
```

该选项执行一次本地嵌入和一次结构化 DeepSeek 生成；提供器可能进行有界重试/格式修复。密钥缺失时不会发送生成请求。预检退出码：`0` 为所请求检查通过，`1` 为依赖或探测失败，`2` 为配置无效/缺少密钥或模式不匹配。

## 无密钥的离线流程演示

完成 Python 安装和数据库初始化后运行；不需要 Ollama 或 DeepSeek key：

```sh
STUDYAGENT_PROVIDER=fake USER_ID=demo-offline SEARCH_PROVIDER=disabled python scripts/preflight.py
STUDYAGENT_PROVIDER=fake USER_ID=demo-offline SEARCH_PROVIDER=disabled uvicorn studyagent.main:app --host 127.0.0.1 --port 8001
```

打开 [http://127.0.0.1:8001](http://127.0.0.1:8001)。顶部明确标记“离线演示 · 非真实模型”。独立 `USER_ID=demo-offline` 隔离其空间；独立端口隔离浏览器本地状态。**数据库仍是真实 PostgreSQL，重启后保留记录**。fake 使用确定性规则生成回答、题目和哈希向量，不是语义模型；真实服务失败也不会自动切换到 fake。

先建立主题为“微积分、导数、梯度和梯度下降”的课程空间，上传仓库自带的 `data/demo_gradient.md`。完整演示步骤见 [docs/demo.md](docs/demo.md)。

## 公共材料与验证

```sh
python scripts/fetch_materials.py
python scripts/evaluate.py
```

材料脚本从 `data/sources.json` 读取清单，默认下载 Transformer / RAG 两份 PDF；`--all` 下载清单中的全部 10 份。PDF 与 SHA-256 清单仅保存在忽略目录 `runtime/materials/`，不会自动上传或进入索引；下载失败会返回非零退出码。清单使用未固定版本的 arXiv 地址，下载字节以 SHA-256 为准，不能将下载成功当作完成标注或评估。

评估脚本运行仓库 pytest，强制使用 fake、模型替身或模拟 HTTP；数据库集成测试仍连接真实 PostgreSQL并新建测试空间。结果写入 `evaluation/results/pytest.xml` 和 `summary.json`，记录测试数量、失败及八类场景对应情况。它不输出“真实回答准确率”。`python scripts/evaluate.py --probe-real` 额外使用当前环境探测真实服务；真实问答质量、人工评分和 baseline 比较仍记为 `not_run`。

详细实现对应 [requirements-map.md](docs/requirements-map.md)，接口见 [api-contract.md](docs/api-contract.md)，材料来源审计见 [material-audit.md](docs/material-audit.md)。

## 数据与停止

上传原件位于 `runtime/`，空间、原始对话、作答、掌握状态和 LangGraph 检查点位于 PostgreSQL。掌握分数是程序启发式，初始值为 unknown，并非经验证的能力估计。切换提供器后应使用独立用户和新空间；真实嵌入与 fake 向量不会混合检索。

按 `Ctrl-C` 停止应用；`docker compose stop` 停止数据库并保留卷。不要用删除数据卷的命令作为演示重置步骤。`.env`、`.venv/`、`runtime/`、本机下载 PDF 和私有附件不应进入源码交付包。

## 本次验证与源码快照

2026-10-27：50 项确定性/fake/模拟 HTTP 测试通过；新 Python 环境、新数据库完成安装、迁移、12 项 HTTP 主流程检查及同一测试集。浏览器已操作上传、带引用追问、答错换例子、再次作答、恢复和停止。真实 Ollama 嵌入返回 768 维向量；DeepSeek 生成和人工内容复核未运行。完整边界及证据见 [进度与验证记录](docs/progress.md)。

```sh
python scripts/package_demo.py
```

打包只包含源码、配置示例、测试、公开材料获取清单、演示说明和脱敏验证记录。`output/StudyAgent-demo.zip` 内的 `VERSION.json` 保存逐文件 SHA-256；同目录 `.sha256` 文件标识 ZIP 字节。没有 Git commit 时使用此清单核验版本。它是 demo 快照，不是包含最终报告与真实评测的正式课程提交包。
