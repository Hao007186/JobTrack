# 階段 6：維運（Operations / Maintenance）

[← 回總覽](architecture.md)｜上一階段：[部署](05-deployment.md)

## 監控與告警（CloudWatch + SNS Email）
| 指標 | 告警條件 |
|---|---|
| Lambda 錯誤率 | 5 分鐘內錯誤 > 5 次 |
| checker 是否有在跑 | 超過 25 小時沒有成功執行 |
| DLQ 訊息數 | > 0 |
| SerpApi／LINE 額度 | 用量 > 80% |
| 通知信寄送失敗 | `alert_deliveries` 出現 `failed`；另外定期看 Resend 主控台的退信與投訴 |
| AWS 費用 | > US$1 |
- 結構化日誌（JSON，帶 request_id、watch_id），用 CloudWatch Logs Insights 查詢
- `/health` 健康檢查端點；Admin 頁面顯示額度、查價覆蓋率（每個 query 距離上次查價幾天）和通知成功率

## 事件處理手冊（runbook）
| 狀況 | 處理方式 |
|---|---|
| SerpApi 額度用完 | 自動暫停查價並發系統通知，下個月 1 號恢復；檢查用量紀錄是否有異常重試 |
| SerpApi key 外洩（出現在 log、Git 或被盜用） | 到 SerpApi 網站重新產生 key（舊的立即失效）→ 更新 SSM Parameter Store（正式）或 `backend/.env`（本機）→ 重新部署；搜尋 CloudWatch log 確認是否還有含 key 的紀錄 |
| SerpApi 停止服務或長期無法使用 | 查價暫停，發系統通知；透過 `PriceProvider` 介面換接其他供應商（例如 Duffel adapter） |
| LINE 推播失敗或額度用完 | 改由 Email 送達；DLQ 告警後人工檢查 |
| Email 寄不出去 | 查 `alert_deliveries` 中 `status = 'failed'` 的 `last_error` → 檢查 Resend 主控台（API key 是否有效、網域驗證與 Cloudflare 的 DNS 記錄是否還在）→ 修好後把這些紀錄改回 `pending` 並把 `attempts` 設為 0 → 執行 `python -m app.jobs.send_notifications` 補寄 |
| Resend 帳號被暫停或停止服務 | 改用其他支援 SMTP 的服務（Gmail SMTP 或 SES），只改 `SMTP_*` 與 `EMAIL_FROM` 設定；檢查退信／投訴原因 |
| 註冊被濫用、價格通知寄到被冒用的信箱（退信率／投訴率告警） | 先暫時關閉註冊；再補上註冊頻率限制或 Cloudflare Turnstile，並對 Lambda 設 reserved concurrency |
| 外部 API 格式改變 | 契約測試會在 CI 失敗；adapter 記錄錯誤並跳過，不影響其他供應商 |
| 部署後出錯 | 依[階段 5〈回滾策略〉](05-deployment.md#回滾策略)回滾 |
| Neon 資料異常 | 剛發生的用 point-in-time restore；其餘從每週的 `pg_dump` 備份（存 S3，保留 4 份）還原 |

## 維護
- **相依套件更新：** Dependabot 每週發 PR，CI 全綠才 merge
- **安全掃描：** CI 加上 `pip-audit`、`npm audit`、Trivy 掃描 image
- **版本發布：** 用 Git tag（語意化版本）+ CHANGELOG（從 Conventional Commits 產生）
- **資料保留：** `price_snapshots` 保留 2 年，超過的由每日排程彙總成每日最低價後刪除，控制在 Neon 0.5GB 內
- **擴充路線：** 日期區間、ArgoCD、Prometheus/Grafana、Duffel adapter、v2 帳號功能

