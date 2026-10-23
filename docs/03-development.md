# 階段 3：開發實作（Development）

[← 回總覽](architecture.md)｜上一階段：[系統設計](02-design.md)｜下一階段：[測試](04-testing.md)

## 專案結構（monorepo）
```
Project_TicketTrack/
├─ backend/app/
│  ├─ core/  db/
│  ├─ modules/{auth,users,watches,prices,providers,alerts,notifications,email,line,admin}/   # 每個模組：router / schemas / models / service
│  ├─ handlers/{api.py,checker.py,notifier.py}                                              # Lambda 進入點
│  └─ alembic/  seeds/（示範帳號資料）  tests/  Dockerfile
├─ frontend/  src/{pages,components,api,hooks}  Dockerfile
├─ deploy/  docker-compose.yml（api + postgres + frontend + MailHog + LocalStack）  helm/farewatch/
├─ infra/terraform/  （ECR、Lambda + Function URL、EventBridge、SQS、S3、CloudFront、ACM、SES、SSM、IAM、CloudWatch、Budgets、Cloudflare DNS）
├─ .github/  workflows/  pull_request_template.md
└─ docs/
```

## 開發規範
- **分支策略：** GitHub Flow。`main` 隨時可部署；功能分支 `feat/*`、`fix/*` → PR → CI 全綠才能 merge（branch protection：需 PR、0 approvals、CI 的 `backend` 與 `docker-build` 必須通過）
- **Commit 格式：** Conventional Commits（`feat:`、`fix:`、`docs:`…），方便自動產生 CHANGELOG
- **程式碼品質：** 後端 ruff + mypy，前端 eslint + prettier；pre-commit hook 在本機先檢查
- **設定管理：** 12-Factor，所有設定走環境變數；`.env.example` 進 Git，`.env` 不進 Git
- **追蹤進度：** GitHub Issues + Projects 看板，每個使用者故事一張卡，依里程碑分組

## 實作順序（依里程碑）

**M0：前置驗證**
- 小實驗（**已完成，2026-10-10**）：拿 5 條台灣出發的航線實際呼叫 Travelpayouts。結果覆蓋率太差，決定不採用、只用 SerpApi，見[總覽〈M0 實驗決策紀錄〉](architecture.md#m0-實驗決策紀錄2026-10-10)。腳本保留在 `experiments/m0/`
- SerpApi 小實驗（**已完成，2026-10-20**）：確認來回票一次呼叫就能拿到總價和 `price_insights`，見[總覽〈M0 SerpApi 實驗紀錄〉](architecture.md#m0-serpapi-實驗紀錄2026-10-20)
- 購買網域、Cloudflare 設定 DNS（寄信服務改到 M1 #5 決定，見[總覽〈2026-10-23 決策紀錄〉](architecture.md#2026-10-23-決策紀錄)）

**M1：MVP 上線**
1. 骨架 + docker-compose + CI（ci.yml）
2. 帳號系統 + 示範帳號（US-01、US-11）
3. 機場／航空公司資料 + 追蹤 CRUD + 生命週期（US-02、US-03）
4. PriceProvider：mock → SerpApi；checker、查詢合併、額度預算與輪流查價（US-10）
5. 價格基準 + 觸發規則 + alerts + notifications + notifier（站內、Email）（US-04、US-06、US-09）
6. 前端頁面 + 價格歷史圖（US-05）
7. Terraform（AWS + Cloudflare）+ deploy pipeline + 基本告警 → **正式上線**

**M2：LINE**
8. LINE 綁定 + Messaging API + webhook（本機用 Cloudflare Tunnel）（US-07、US-08）

**M3：k8s 與 E2E**
9. Helm chart + kind 冒煙測試 + Playwright E2E 進 CI（見[階段 4](04-testing.md)、[階段 5](05-deployment.md)）

**M4：維運強化**
10. 完整監控告警、v2 帳號功能、Dependabot、安全掃描、README

