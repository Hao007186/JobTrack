# Claude Code 可用 Skills 一覽

> 整理日期：2026-10-09
> Skill 是預先寫好的工作流程或專業知識包。Claude 遇到相關任務時會自動載入，你也可以輸入 `/skill名稱` 手動觸發。

## 如何使用

- **手動觸發**：在對話框輸入 `/brainstorming`、`/code-review` 等。
- **自動觸發**：直接描述需求（例如「幫我除錯這個 bug」），Claude 會判斷要不要載入相關的 skill。
- **plan 模式下**：只讀型和討論型的 skill 可以正常使用；需要寫檔、執行指令或 commit 的步驟，要等離開 plan 模式後才會執行。

---

## 1. 開發流程（superpowers 外掛）

存放位置：`C:\Users\User\.claude\plugins\cache\superpowers-marketplace\superpowers\<版本>\skills\`

| Skill | 用途 | 適用時機 |
|---|---|---|
| `brainstorming` | 釐清需求、比較方案、產出設計規格 | 開始做任何新功能前 |
| `writing-plans` | 把需求拆成按部就班的實作計畫 | 有規格、準備動手寫程式前 |
| `executing-plans` | 照計畫一步步實作 | 計畫完成後，在同一個 session 裡自己做 |
| `subagent-driven-development` | 把計畫中的任務分給子 agent 執行 | 計畫中有多個獨立任務時 |
| `dispatching-parallel-agents` | 同時派出多個 agent 處理互不相依的工作 | 有 2 個以上可平行的工作 |
| `test-driven-development` | 先寫測試，再寫實作 | 實作功能或修 bug 時 |
| `systematic-debugging` | 有系統地找出問題根本原因 | 遇到 bug、測試失敗、怪異行為 |
| `verification-before-completion` | 宣稱完成前，實際跑驗證指令 | commit 或發 PR 前 |
| `requesting-code-review` | 請人審查程式碼 | 完成重要功能、合併前 |
| `receiving-code-review` | 理性評估審查意見，不盲目照做 | 收到 review 回饋時 |
| `using-git-worktrees` | 開一個隔離的工作區 | 開發新功能、避免影響主分支 |
| `finishing-a-development-branch` | 決定分支怎麼收尾（合併、發 PR、清理） | 功能完成、測試通過後 |
| `writing-skills` | 撰寫、測試自訂 skill | 想建立自己的 skill |
| `diagnosing-superpowers` | 分析 session 為什麼出問題 | 覺得 Claude 做得慢、重複或不照計畫 |

**建議流程：**
```
brainstorming → writing-plans → (using-git-worktrees) → executing-plans + test-driven-development
→ verification-before-completion → requesting-code-review → finishing-a-development-branch
```

---

## 2. 程式碼品質（Claude Code 內建）

| Skill | 用途 |
|---|---|
| `code-review` | 審查目前的變更或 PR，找出正確性問題。可指定強度 `low`～`max`；`ultra` 會在雲端用多個 agent 深度審查 |
| `simplify` | 精簡程式碼、去除重複，並直接套用修改（不負責找 bug） |
| `security-review` | 對目前分支的變更做安全性審查 |

---

## 3. 專案與環境設定（Claude Code 內建）

| Skill | 用途 |
|---|---|
| `init` | 分析專案，產生 `CLAUDE.md` 說明檔 |
| `run` | 啟動 app，實際確認改動有效 |
| `update-config` | 修改 `settings.json`（權限、hooks、環境變數） |
| `fewer-permission-prompts` | 分析歷史紀錄，自動加入常用指令的允許清單 |
| `keybindings-help` | 自訂快捷鍵 |
| `loop` | 定時重複執行某個指令（例如每 5 分鐘檢查一次） |
| `schedule` | 建立雲端排程 agent（cron） |
| `plugin-authoring` | 撰寫 Claude Code 外掛（狀態列、hooks 等） |
| `claude-api` | Claude API / Anthropic SDK 參考資料 |

---

## 4. 文件與輸出（從 claude.ai 同步）

存放位置：`C:\Users\User\.claude\skills\synced\...\`

| Skill | 用途 |
|---|---|
| `docs` | 建立可分享、可留言的線上文件 |
| `docx` | 產生或編輯 Word 檔 |
| `pdf` | 讀取、合併、分割、建立 PDF |
| `pptx` | 產生或編輯 PowerPoint 簡報 |
| `xlsx` | 產生或編輯 Excel 試算表 |
| `google-workspace` | 編輯 Google 文件、試算表、簡報 |
| `deep-research` | 多來源研究，整理成報告 |
| `skill-creator` | 建立、改良、評測 skill |
| `import-memory` | 從其他 AI 助理匯入記憶 |
| `morning` | 產生每日晨報 |

---

## 5. 網頁、圖表與瀏覽器

| Skill | 用途 |
|---|---|
| `artifact-design` | 設計可分享的網頁（Artifact） |
| `artifact-diagramming` | 畫架構圖、流程圖 |
| `artifact-capabilities` | 讓網頁有資料庫、多人共享等互動功能 |
| `dataviz` | 製作圖表、儀表板 |
| `built-in-browser` | 使用桌面版 app 內建的瀏覽器 |
| `chrome-browser` | 透過 Chrome 擴充功能操作瀏覽器 |
| `computer-use` | 操作電腦上的桌面 app |

---

## 對本專案（最低價機票通知網站）特別有用的

| 階段 | 推薦 Skill |
|---|---|
| 需求與架構規劃 | `brainstorming`、`deep-research`（調查機票 API 或爬蟲方案） |
| 拆解實作步驟 | `writing-plans` |
| 開發爬價、通知功能 | `test-driven-development`、`executing-plans` |
| 價格走勢圖 | `dataviz` |
| 除錯 | `systematic-debugging` |
| 上線前 | `code-review`、`security-review`、`verification-before-completion` |
| 定期查價測試 | `loop`、`schedule` |

---

## 新增專案專屬 Skill

在專案中建立以下結構，即可新增只給這個專案用的 skill（可提交到 git 與團隊共用）：

```
Project_TicketTrack/
└── .claude/
    └── skills/
        └── <skill名稱>/
            └── SKILL.md
```

可以用 `skill-creator` 協助建立。
