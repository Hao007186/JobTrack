# 階段 4：測試（Testing）

[← 回總覽](architecture.md)｜上一階段：[開發實作](03-development.md)｜下一階段：[部署](05-deployment.md)

## 測試金字塔
| 層級 | 工具 | 範圍 | 目標 |
|---|---|---|---|
| 單元測試 | pytest、Vitest | 價格基準、觸發規則與狀態轉換、額度預算計算、查詢合併、JWT、元件 | 核心邏輯（prices、alerts）覆蓋率 ≥ 90%，整體 ≥ 70% |
| 整合測試 | pytest + 真實 Postgres（CI service container）、httpx mock 外部 API | API 端點、DB 交易、Alembic migration、LINE 簽章驗證、來源驗證標頭 | 每個端點都有正常、錯誤和權限案例 |
| 契約測試 | 錄製的 SerpApi 回應（fixtures，含有／沒有 `price_insights` 兩種） | adapter 能正確解析真實格式 | 供應商改格式時能及早發現 |
| E2E 測試 | **Playwright**（M3） | 註冊 → 建立追蹤 → mock 降價 → 通知中心出現通知；示範帳號瀏覽 | 核心流程 3–5 條 |
| k8s 冒煙測試 | kind + Helm（M3） | 部署後 API 健康檢查 + checker 跑一次 | 每個 PR |

## 必測案例
- 安全：token 過期／撤銷、帳號鎖定、使用者 A 讀不到 B 的追蹤、非 admin 打 admin API 回 403、示範帳號寫入回 403、綁定 `state` 遭竄改時拒絕、webhook 簽章錯誤回 401、缺少或錯誤的 `X-Origin-Verify` 回 403、refresh token 被重用時作廢該使用者所有 token
- 觸發規則：三種觸發原因、新追蹤第一次確認就低於目標價會通知 1 次、連續小幅創新低不重複通知、同一筆價格符合多個原因只產生一則 alert、跌破目標價只通知 1 次、再降 ≥5% 才再通知、回升後再跌破會重新通知、樣本不足時不判斷歷史新低、沒有 `price_insights` 時只用目標價
- 額度：每日預算計算、最久沒查的 query 優先、預算用完就停止本次查價、額度歸零時暫停查價並發系統通知、超過每人 3 個追蹤時拒絕新增、全站滿 8 個 query 時新追蹤進入排隊且不被查價、對應到既有 query 的新追蹤不必排隊、人數不同的追蹤不合併成同一個 query
- 生命週期：出發前 2 天停止查價、出發後自動 expired、編輯追蹤後重新對應 price_query 並重置通知狀態、有空位時依建立時間啟用排隊中的追蹤、示範資料不被查價
- 可靠性：SQS 重送不重複發送
- 外部 API 一律 mock，CI 不消耗真實額度

