# 階段 5：部署（Deployment）

[← 回總覽](architecture.md)｜上一階段：[測試](04-testing.md)｜下一階段：[維運](06-operations.md)

## 環境
| 環境 | 內容 |
|---|---|
| local | docker-compose（Postgres、MailHog、LocalStack SQS、mock provider） |
| k8s-demo | kind + Helm（本機和 CI，M3） |
| prod | AWS Serverless + Neon + Cloudflare DNS |

（單人專案不另外建 staging；Neon 免費版可以開 branch，給 migration 預演用）

## 一次性手動設定（寫進部署文件）
- 購買網域，將 DNS 交給 Cloudflare 管理
- 申請 SES 正式使用權限（說明用途、退信與投訴處理方式）
- 建立 LINE Provider，並在其下建立 Login channel 和 Messaging API channel
- 建立 Terraform state 用的 S3 bucket（避免雞生蛋問題，不由 Terraform 自己建立）

## CI/CD
- `ci.yml`（PR）：lint + 型別檢查 + 單元／整合測試 + 前端 build + docker build + `terraform fmt/validate/plan`
- `k8s-e2e.yml`（PR，M3）：建 amd64 image 並 `kind load`（不推 ECR）→ `helm install` → 冒煙測試 + Playwright E2E
- `deploy.yml`（merge 到 main）：`buildx` 建 arm64 單一架構 image（`--provenance=false`）推上 ECR（tag = git SHA）→ 在 Neon branch 預演 migration → `alembic upgrade head` → `terraform apply` 更新 Lambda → 前端 `s3 sync` + CloudFront invalidation → 部署後冒煙測試
- AWS 認證用 GitHub OIDC（不存長期金鑰）；Cloudflare API token 存在 GitHub Secrets（權限只限該網域的 DNS）

## 回滾策略
- 程式：Lambda 改回上一個 image tag（ECR 保留 3 個版本）→ `terraform apply -var image_tag=<上一版>`
- 資料庫：migration 一律向後相容（先加欄位、再改程式、最後才刪欄位）；資料救援以每週 `pg_dump` 備份為主，Neon 免費版的 point-in-time restore 視窗很短（實作時確認當時的額度），只能救剛發生的誤操作
- 前端：S3 開啟版本控制，可以還原上一版

## 成本控管
- **網域**：約 US$10／年（唯一固定支出）
- **AWS 免費方案期間**（新帳號最多 6 個月）：費用由抵用金支付，信用卡不會被扣款。**到期或抵用金用完之前必須升級成付費方案，否則帳號會被關閉**
- **之後**：ECR、S3、SES 每月幾分錢，其他都在永久免費額度內

| 會產生費用的項目 | 怎麼避免 |
|---|---|
| API Gateway（免費額度只有 12 個月） | 改用 Lambda Function URL |
| Route 53 hosted zone（每月 US$0.50） | DNS 放 Cloudflare |
| ECR 儲存費 | lifecycle 規則只保留 3 個 image |
| Secrets Manager | 改用 SSM Parameter Store 標準版 |
| CloudWatch Logs 超過 5GB | log 只保留 7–14 天 |
| NAT Gateway | Lambda 不放進 VPC |
| KMS 自訂金鑰 | 使用 AWS 管理的金鑰 |
| SerpApi 超量 | 硬上限 250 次，用完降級，不升級付費 |
| 忘記關掉的資源 | AWS Budgets US$1 告警 + 全部用 Terraform 管理 |
| 免費方案到期，帳號被關閉 | 到期前升級成付費方案（設行事曆提醒），升級後靠 Budgets US$1 告警把關 |

