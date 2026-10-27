# Actual development prompt record (redacted)

2026-10-26 user request: build a runnable StudyAgent from the supplied proposal, course guideline, and five ZIPs covering three exercise topics, plus the repository; inspect real inputs, implement a single Orchestrator + tools + persistent state, Course/Focus/General Chat, verified RAG, graph, adaptive quiz loop, context/memory, local UI and honest testing. Local-only, no commit/push/deploy. Detailed original request is retained in this Codex chat; this is a scope summary, not a verbatim transcript.

Actual follow-up: “这个先不填写，我现在只需要做一个demo”; “用deepseek”; “尚未配置” (DeepSeek key).

Agent delegation 1: Static audit of two PDFs and five ZIPs; read page contents, notebook prompts and L05/L06 stubs; do not execute archive code, preserve originals; record page/function evidence and omissions in docs/material-audit.md.

The coding-model identifier is not exposed reliably by the task runtime. Tool environment: Codex desktop, shell, GitHub connector, official web documentation, parallel coding agents. No claim of capturing earlier conversations or every internal model instruction. No AI responses are required by the course guideline.

2026-10-27 actual user continuation: “继续”. Additional user constraints: prefer minimal reversible implementation, preserve existing work, no commits without explicit instruction, verify actual changes. This sentence summarizes the supplied AGENTS.md and is not its verbatim text.

2026-10-27 actual delegated review prompt (verbatim):

> 继续做只读交付审查（不修改代码/文档）：核对 README、docs/demo.md、requirements-map、ai-use、prompts/development-log 与当前源码/测试 evidence 的真实边界，找出任何误报已验证、泄漏个人敏感信息、缺启动必要文件或命令问题。当前 clean-room.json 已完整 status passed，50 tests，12 HTTP checks。给出必要修正；无需重跑下载/测试。重点用户已缩到 demo，无 DeepSeek key。

Earlier provider/frontend/review subagent prompts are not fully reproduced in this file. Their development assistance is acknowledged in `docs/ai-use.md`; no invented verbatim history is supplied.
