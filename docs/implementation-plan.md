# StudyAgent Demo Implementation Plan

> Execution: superpowers:subagent-driven-development; final verification: superpowers:verification-before-completion. No commits or remote writes.

**Goal:** 可交互的单用户本地中文 demo，真实 DeepSeek 语义判断、独立 embedding、真实 PostgreSQL 和持久 LangGraph；缺 key 时明确标记 fake 流程测试。

**Architecture:** FastAPI 同源静态 UI → application service → LangGraph / tools → PostgreSQL + pgvector。客户端只收公开 quiz；服务端评分。对 session 使用 PostgreSQL advisory lock 跨进程串行；attempt 唯一约束与事务幂等。上传和网页分别验证；共享服务支持 Course/Focus/Chat。

**Tech Stack:** Python 3.12、FastAPI、LangGraph + PostgresSaver、psycopg、pgvector、PyMuPDF、httpx；原生 HTML/CSS/JS 无 npm 构建。

## Chunk 1: 材料、基础和契约
- [x] 静态检查真实附件、空本地仓库及空私有 GitHub，读取原提示词。
- [x] `studyagent/config.py`, `db.py`, `schemas.py`, `migrations/001_initial.sql`, `compose.yaml`, `requirements.lock`。输入 env；输出 DB schema、严格 Pydantic 契约；验收连接、迁移可重跑、版本锁定。
- [x] `studyagent/providers.py`, `context.py`, `prompts/system.txt`。DeepSeek JSON、Ollama embedding、限时重试、fake 显式模式、最终输入 token；验收超时/坏 JSON/维度/预算。

## Chunk 2: 纵向流程和范围
- [x] `studyagent/knowledge.py`。输入 PDF/TXT/MD + space；输出验证状态、pgvector chunks、图和来源。问答返回实际证据引用；不确定材料隔离。依赖 db/provider；验收重复、冲突、跨空间、证据不充分。
- [x] `studyagent/learning.py`, `main.py`。创建会话→检索→选模式→生成 quiz→interrupt→Command resume→评分事务→重新规划。依赖上项；验收答错切例子、重复成功、停止、重启、重复/过期/并发提交、答案不泄漏。
- [x] preference memory + chat context：来源范围、修订无效化、历史追加、保护纠正；验收召回范围与输入内容。

## Chunk 3: 交互和 demo
- [x] `studyagent/static/{index.html,app.js,style.css}`。真实 API，中文界面、空间/上传/问答/引用/图/测验/恢复/停止/Focus 入课；无前端答案；验收浏览器端到端、窄屏、键盘与错误状态。
- [x] `tests/`, `scripts/preflight.py`, `scripts/evaluate.py`, `evaluation/scenarios.json`。先固定输入预期，再运行；区分 deterministic/fake/real。至少外部失败与重启/重复提交故障。baseline 共享检索模型只比回答引用。
- [x] `README.md`, `docs/progress.md`, `docs/requirements-map.md`, `docs/demo.md`, `docs/ai-use.md`, `prompts/development-log.md`。准确入口、服务预检、限制、实际验证证据。

## 当前范围调整（用户 2026-10-26）
先做 demo；组号/分工/人工评审不填写。完整课程报告 PDF、最终源码提交 ZIP 和完整 8–12 文档重复实验在 demo 稳定后处理，不把它们写成已完成。先准备公开资料清单和可复现实验入口。

## 验收原则
运行隔离新 DB 和干净目录安装/迁移/启动/主流程；不影响现有 COMP7104 数据库。真实服务失败不回退 fake。测试证据来自本次运行，不使用练习历史日志。原始附件不复制入仓库，学号不入文档。

## 当前验收结论

上述勾选表示实现与确定性/fake 验收完成。真实 DeepSeek 验收仍待本地 key；50 项测试、隔离安装及浏览器流程证据见 `docs/progress.md`。当前仅生成 demo 源码快照，正式课程报告/评测提交包仍延期。
