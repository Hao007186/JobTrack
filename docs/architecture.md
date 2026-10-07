# JobTrack 求職紀錄網站 — 架構規劃

## Context
建立多使用者（初期 ≤100 人，保留擴充空間）的求職紀錄網站：求職者註冊/登入、維護技能、記錄應徵工作與狀態，系統依「技能 × 職缺要求技能」計算匹配度，並統計面試邀請率與成功率。
定位為**作品集／學習**，完整展示 前端 / 後端 / SQL / Docker / CI/CD / AWS，AWS 成本壓在免費額度或極低成本。
為了未來可擴充成求職網站，**現在就把職缺與應徵分離，並實作最小企業端**（企業刊登職缺、查看應徵者與匹配度、更新應徵狀態）。工作目錄 `c:\Users\User\Project_JobTrack` 目前為空專案。

## 技術選型
| 層 | 選擇 |
|---|---|
| 前端 | React + TypeScript + Vite、React Router、TanStack Query、Recharts、Tailwind |
| 後端 | Python FastAPI、SQLAlchemy 2.0 + Alembic、Pydantic、PyJWT、pwdlib(Argon2) |
| 資料庫 | PostgreSQL 16（本地 Docker；雲端 RDS） |
| 測試 | pytest + httpx；Vitest + React Testing Library |
| 容器 | backend / frontend 各自 multi-stage Dockerfile、docker-compose 本地開發 |
| CI/CD | GitHub Actions（AWS 認證用 OIDC） |
| 雲端 | EC2 + RDS + S3 + CloudFront + ECR + SSM Parameter Store |

**為何 PostgreSQL**：開源免費、與 FastAPI/SQLAlchemy/Alembic 搭配最成熟、DDL 可交易（migration 失敗整批回滾）、原生 ENUM/CHECK/部分索引/全文搜尋、Docker 映像輕量、RDS 成本最低。

## AWS 部署（作品集取向）
```
使用者 ─HTTPS─► CloudFront ─► S3（React 靜態檔）
                   │ /api/*
                   ▼
              EC2 (t4g.small)  Docker：Nginx + FastAPI
                   │ 私有子網路
                   ▼
              RDS PostgreSQL (db.t4g.micro)
```
擴充路線：EC2 → ECS Fargate + ALB（同一 image）；全文搜尋 → OpenSearch；履歷檔 → S3；通知/寄信 → SQS + worker；RDS read replica、Redis 快取。

## 後端架構：模組化單體
```
backend/app/
├─ core/        設定、安全(JWT/雜湊)、權限 dependency
├─ db/          session、base model
└─ modules/
   ├─ auth/          註冊、登入、refresh、登出
   ├─ users/         個人資料、技能
   ├─ organizations/ 企業與成員
   ├─ skills/        技能主表
   ├─ jobs/          職缺（job_postings）
   ├─ applications/  應徵與狀態歷史
   ├─ matching/      匹配演算法（純函式）
   ├─ stats/         統計
   └─ admin/         管理功能
```
每個模組內含 `router.py / schemas.py / models.py / service.py`。模組之間只透過 service 互相呼叫。

## 資料表設計標準
1. 正規化至 3NF；2. snake_case、表名複數、FK `<單數>_id`；3. 主鍵 `BIGINT IDENTITY`，對外用 `public_id UUID`；
4. FK / NOT NULL / UNIQUE / CHECK 約束；5. `created_at`、`updated_at`（timestamptz），主要資料加 `deleted_at` 軟刪除；
6. FK 與常用查詢欄位加索引；7. Schema 變更只走 Alembic；8. 密碼只存 Argon2 雜湊。

## 資料模型
**帳號與權限**
- `users`(id, public_id, email UQ, password_hash, display_name, is_active, email_verified_at, failed_login_count, locked_until, timestamps)
- `roles`(id, name UQ)：`job_seeker`、`employer`、`admin`
- `permissions`(id, code UQ)、`role_permissions`、`user_roles`
- `refresh_tokens`(id, user_id, token_hash, expires_at, revoked_at)

**企業**
- `organizations`(id, public_id, name, website, description, timestamps)
- `organization_members`(organization_id, user_id, member_role[owner/recruiter])

**技能**
- `skills`(id, name UQ, normalized_name)
- `user_skills`(user_id, skill_id, proficiency 1–5)

**職缺與應徵**
- `companies`(id, name, normalized_name, organization_id NULL)：求職者手動輸入的公司名稱；若該公司已入駐平台，關聯到 organization
- `job_postings`(id, public_id, title, description, location, url, company_id, organization_id NULL, source[`personal`/`platform`], visibility[`private`/`public`], status[`open`/`closed`], created_by, timestamps)
  - `personal`：求職者為自己建立的紀錄，`visibility=private`，只有建立者看得到
  - `platform`：企業刊登的職缺，`visibility=public`
- `job_posting_skills`(job_posting_id, skill_id, importance 1–3)
- `applications`(id, public_id, user_id, job_posting_id, current_status, applied_at, notes, timestamps)，UQ(user_id, job_posting_id)
- `application_status_history`(id, application_id, from_status, to_status, changed_by, changed_at)
- 狀態 enum：`applied`、`screening`、`interviewing`、`offered`、`accepted`、`rejected`、`withdrawn`

## 驗證與權限
**驗證（分階段）**
- 第一版：帳密註冊/登入（註冊時選擇求職者或企業）、Argon2、JWT access token（15 分鐘）+ refresh token（7 天，存 DB 可撤銷，放 HttpOnly Cookie）、登出、登入失敗鎖定
- 第二版：Email 驗證 + 忘記密碼（AWS SES；本地用 MailHog）
- 選做：Google OAuth（Authlib）、TOTP（pyotp）

**授權（RBAC + 資料擁有權）**
| 角色 | 權限 |
|---|---|
| job_seeker | 管理自己的技能、建立個人職缺紀錄、瀏覽公開職缺、應徵、查看自己的匹配度與統計 |
| employer | 管理所屬組織資料、刊登/關閉職缺、查看「自家職缺」的應徵者（含技能與匹配度）、更新這些應徵的狀態 |
| admin | 停用帳號、指派角色、審核組織、合併技能主表、查看全站匿名統計 |
- 後端以 dependency `get_current_user`、`require_permission(code)` 加上 owner/organization 檢查實作；前端依角色切換路由與選單，但以後端檢查為準
- 隱私：求職者只有在應徵平台職缺時，才把技能分享給該企業；企業看不到求職者的個人紀錄（personal postings）

**狀態更新規則**
- `personal` 職缺：由求職者自行更新狀態
- `platform` 職缺：由企業更新狀態；求職者只能撤回（`withdrawn`）
- 每次變更都寫入 `application_status_history`（記錄 changed_by）

## 核心邏輯
**匹配度**（`modules/matching`，通用函式：技能清單 × 職缺要求技能清單）
```
score = Σ importance_s × min(proficiency_s, 期望值)/期望值 ÷ Σ importance_s → 0–100%
```
同時回傳已具備與缺少的技能。求職者端看「我對這個職缺」的匹配度，企業端依匹配度排序應徵者，兩邊共用同一個函式。

**統計**
- 求職者：面試邀請率 = 曾達 `interviewing` 以上的應徵數 ÷ 總應徵數（依 status_history 判斷）；成功率 = `offered`/`accepted` 數 ÷ 總應徵數（另提供 ÷ 已有結果數的口徑）；月趨勢；各匹配度區間的面試率
- 企業：每個職缺的應徵數、各狀態漏斗
- 管理員：全站匿名彙總
- 百人規模直接用 SQL 聚合

## API 草案（/api/v1）
- Auth：`POST /auth/register|login|refresh|logout`、`GET /auth/me`
- 求職者：`GET/PUT /me/skills`、`GET /me/stats`
- Skills：`GET /skills?q=`
- Jobs：`GET /jobs`（公開職缺，支援搜尋/篩選）、`GET /jobs/{id}`、`POST /me/jobs`（個人職缺紀錄）
- Applications：`GET/POST /me/applications`、`GET/PATCH/DELETE /me/applications/{id}`、`POST /me/applications/{id}/status`、`GET /me/applications/{id}/match`
- Employer：`GET/PATCH /org`、`GET/POST /org/jobs`、`PATCH /org/jobs/{id}`、`GET /org/jobs/{id}/applicants`（依匹配度排序）、`POST /org/applications/{id}/status`、`GET /org/stats`
- Admin：`GET /admin/users`、`PATCH /admin/users/{id}`、`PATCH /admin/organizations/{id}`、`POST /admin/skills/merge`、`GET /admin/stats`

## 前端頁面
- 共用：登入、註冊（選擇角色）
- 求職者：儀表板（統計圖表）、我的技能、我的應徵（列表/看板 + 詳情 + 匹配度）、職缺瀏覽
- 企業：組織資料、職缺管理、應徵者列表（依匹配度排序、更新狀態）、職缺統計
- 管理員：使用者管理、組織審核、技能主表維護

## 專案結構（monorepo）
```
Project_JobTrack/
├─ backend/   app/（如上）、alembic/、tests/、Dockerfile
├─ frontend/  src/{pages/{seeker,employer,admin},components,api,hooks}、Dockerfile
├─ infra/     nginx.conf、(terraform/)
├─ .github/workflows/  ci.yml、deploy.yml
├─ docker-compose.yml
└─ README.md（架構圖、啟動方式、設計取捨、擴充路線）
```

## CI/CD
- `ci.yml`（每個 PR）：ruff + mypy + pytest（Postgres service container）、eslint + vitest + build、docker build
- `deploy.yml`（merge 到 main）：backend image → ECR → 透過 SSM 讓 EC2 執行 `docker compose pull && up -d` + `alembic upgrade head`；frontend → `aws s3 sync` + CloudFront invalidation

## 實作階段
1. 專案骨架 + docker-compose（FastAPI + Postgres + React）
2. Schema 與 migration；驗證（JWT/refresh/鎖定）+ RBAC 三種角色 + seed 資料
3. 技能、個人職缺紀錄、應徵 CRUD、狀態歷史
4. 匹配度 + 求職者統計
5. 求職者前端頁面
6. 企業端：組織、職缺刊登、應徵者列表、狀態更新、職缺統計（後端 + 前端）
7. 管理員功能
8. CI pipeline
9. AWS 建置 + deploy pipeline
10. Email 驗證/忘記密碼（第二版）、README/架構圖、（選做）Terraform、OAuth、TOTP

## 預設假設
- 個人職缺紀錄的技能由使用者手動勾選，不做爬蟲/AI 解析
- 企業註冊後需管理員審核組織才能刊登職缺（防止濫用）
- 首版不做履歷檔案上傳、站內訊息與即時通知（列為擴充）

## 驗證方式
- 本地 `docker compose up`：求職者註冊 → 建技能 → 建個人職缺並應徵 → 更新狀態 → 檢查匹配度與統計；企業註冊 → admin 審核 → 刊登職缺 → 求職者應徵 → 企業依匹配度看到應徵者並更新狀態 → 求職者端狀態同步
- pytest：auth（token 過期/撤銷/鎖定）、權限隔離（求職者 A 讀不到 B 的資料；企業看不到其他組織的應徵者與求職者的個人紀錄；非 admin 打 admin API 回 403）、匹配度、統計口徑、狀態更新規則
- CI 全綠；部署後透過 CloudFront 網址做一次端到端操作
