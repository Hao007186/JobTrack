# FareWatch（repo：Project_TicketTrack）

最低價機票即時通知網站，單人維護的展示型作品集。
產品名稱是 **FareWatch**，repo 資料夾名稱是 `Project_TicketTrack`，兩者指同一個專案。

## 目前狀態
- **M0 前置驗證**進行中：只有 `experiments/m0/` 的小實驗腳本，正式的 backend／frontend 程式碼從 M1 才開始寫
- 架構文件是草稿第 3 版：`docs/architecture.md` 是總覽，`docs/01-requirements.md` ~ `docs/06-operations.md` 是 SDLC 6 個階段

## 何時讀哪份文件
- 做需求、架構、設計、實作相關的工作前，先讀 `docs/architecture.md`，再依工作內容讀對應的階段文件
- `docs/skills.md`：可用的 Claude Code skills 一覽

## 規範
- 文件與回覆使用繁體中文
- Commit 格式用 Conventional Commits（`docs:`、`feat:`、`fix:`…）
- 分支策略用 GitHub Flow：從 `main` 開分支，經 PR 合併
