# M1 子專案 #5：觸發規則 + alerts + 通知 + notifier — 設計

日期：2026-10-24
狀態：待審閱
相關文件：[architecture.md](../../architecture.md)、[02-design.md](../../02-design.md)、[#3 追蹤功能設計](2026-10-23-m1-watches-design.md)、[#4 查價設計](2026-10-23-m1-prices-design.md)

## 背景與目標
M1 的第 5 個子專案：查到價格後套用觸發規則、產生 alert、站內通知中心、Email 寄送（notifier），以及前面子專案留下的系統通知與通知狀態重置。對應 US-06、US-09（Email 開關）。

**完成標準：**
- 下方〈測試〉列出的案例全部通過；測試不連網路、不寄真的信
- 本機用 mock 執行 `python -m app.jobs.check_prices` 後，符合條件的追蹤產生站內通知，console 寄信器在 log 印出信件
- 設定 Resend 後手動寄出一封真的價格通知信，確認收得到、連結正確
- 示範帳號登入就看得到通知
- PR 上的 CI 全綠

## 不在範圍內
LINE 推播與 `line_enabled`（M2）；管理員用量頁 US-10（繼續延後）；HTML 信件；SQS 與排程的觸發（#7）；AWS 帳號驗證（只影響 #7）。

## 設計決定
| 項目 | 決定 | 理由 |
|---|---|---|
| 寄信服務 | 通用 SMTP 寄信器，實測接 **Resend**（從自己的網域寄）；本機預設 console 寄信器 | AWS 帳號尚未驗證；Resend、Gmail、SES 都支援 SMTP，之後換服務只改設定。Resend 免費版每天 100 封，對本人和極少數使用者綽綽有餘 |
| checker 與 notifier 的交接 | **DB 當寄件匣（outbox）**：checker 在寫入快照的同一個 transaction 內寫入 alert、站內通知與 `pending` 的寄送紀錄；notifier 讀出 `pending` 的紀錄寄出 | 不會出現「alert 寫了、通知卻漏掉」；重試與冪等都靠 DB；不依賴 AWS。#7 的 SQS 或排程只負責叫醒 notifier |
| 站內通知由誰寫 | checker（同一個 transaction）；notifier 只負責外部管道 | 站內通知只是一筆 DB 資料，不需要等外部服務；修正 02-design「notifier 寫入 notifications」的描述 |
| 系統通知 | 只發站內通知，不寄 Email；額度用完時發給受影響的使用者，每人每月一次 | Email 只留給價格通知，避免信箱被系統訊息打擾 |
| 通知狀態的初始值 | `watch_alert_states` 沒有資料 = 初始狀態；重置 = 刪掉那筆 | 不用在建立追蹤時多寫一筆，重置也不用列出每個欄位的初始值 |

## 資料表
| 表 | 欄位 | 說明 |
|---|---|---|
| `watch_alert_states` | watch_id（PK、FK → watches，ON DELETE CASCADE）、below_target（預設 false）、below_typical（預設 false）、last_notified_price（NULL 可）、last_notified_at（`timestamptz`，NULL 可） | 沒有資料 = 兩個狀態都是 false、從未通知過 |
| `alerts` | id、watch_id（FK，CASCADE）、snapshot_id（FK → price_snapshots，NULL 可，ON DELETE SET NULL）、reason（`below_target`／`record_low`／`below_typical`）、price、created_at；UQ(watch_id, snapshot_id) | 價格警示的業務紀錄；`reason` 是主要原因 |
| `notifications` | id、public_id（UUID，UQ）、user_id（FK → users，CASCADE）、type（`price_alert`／`system`）、title、body、link（NULL 可）、alert_id（FK，NULL 可，ON DELETE SET NULL）、dedupe_key（NULL 可）、is_read（預設 false）、created_at；UQ(user_id, dedupe_key)；index(user_id, created_at DESC) | 站內通知中心；`dedupe_key` 防止系統通知重複（NULL 不受唯一鍵限制） |
| `alert_deliveries` | id、alert_id（FK，CASCADE）、channel（v1 只有 `email`）、status（`pending`／`sent`／`failed`／`skipped`）、attempts（預設 0）、last_error（Text，NULL 可）、sent_at（NULL 可）、created_at；UQ(alert_id, channel) | 每則 alert 在每個管道的寄送狀態 |
| `notification_settings` | user_id（PK、FK，CASCADE）、email_enabled（預設 true） | 沒有資料 = 全部預設值 |

刪除追蹤時：通知狀態、alerts、寄送紀錄一起刪除；站內通知保留，`alert_id` 變 NULL。

和 02-design 的差異：`notifications` 加 `public_id`、`dedupe_key`；`alert_deliveries` 加 `id`、`last_error`、`created_at`；`notification_settings` 暫不加 `line_enabled`（M2）。

## 觸發規則（`app/modules/alerts/rules.py`，純函式，不碰 DB）
```python
@dataclass(frozen=True)
class AlertState:
    below_target: bool = False
    below_typical: bool = False
    last_notified_price: int | None = None

@dataclass(frozen=True)
class BaselineView:
    typical_low: int | None        # 這次更新後的典型區間下緣
    record_low_before: int | None  # 這筆價格併入之前的歷史最低
    history_ready_before: bool     # 這筆價格併入之前是否已足夠判斷歷史新低

@dataclass(frozen=True)
class Decision:
    notify: bool
    reasons: tuple[str, ...]       # 依優先順序排列；notify 為 False 時為空
    new_state: AlertState

def evaluate(state: AlertState, price: int, target_price: int, baseline: BaselineView) -> Decision: ...
```

1. 本次條件：
   - `is_below_target = price <= target_price`
   - `is_below_typical = typical_low is not None and price < typical_low`
   - `is_record = history_ready_before and record_low_before is not None and price < record_low_before`
2. 狀態變化：`newly = (is_below_target and not state.below_target) or (is_below_typical and not state.below_typical)`
3. 是否通知：
   - `newly` → 通知
   - 否則三個條件有任一成立：`last_notified_price is None` → 通知；否則 `price * 100 <= last_notified_price * 95` 才通知（整數運算，避免浮點誤差）
   - 都不成立 → 不通知
4. `reasons`：成立的條件依 `below_target` > `record_low` > `below_typical` 排序；`reasons[0]` 寫進 `alerts.reason`
5. 新狀態：`below_target = is_below_target`、`below_typical = is_below_typical`（價格回升就重置）；通知時 `last_notified_price = price`，否則保留

「歷史新低」要跟併入前的值比：`apply_result` 會先把這筆價格併進 `record_low`，所以 checker 在呼叫 `apply_result` 前先記下 `record_low` 與 `history_ready(baseline)`。

## 套用規則（`app/modules/alerts/service.py`）
`record_result` 寫入快照並 flush（取得 snapshot id）、更新基準之後、commit 之前，呼叫：

```python
async def evaluate_watches(session, query, snapshot, baseline_view, now) -> int  # 回傳產生的 alert 數
```

- 只處理該 query 底下 `status = 'active'` 的追蹤；查不到航班時不呼叫
- 對每個追蹤：讀 `watch_alert_states`（沒有就用初始值）→ `evaluate` → 寫回狀態（upsert）
- 需要通知時，同一個 transaction 內：
  1. 寫入 `alerts`（`INSERT ... ON CONFLICT (watch_id, snapshot_id) DO NOTHING`；衝突就略過後續步驟）
  2. 寫入 `notifications`（type `price_alert`，`alert_id` 指向它）
  3. 使用者的 `email_enabled` 為 true（沒有設定 = true）→ 寫入 `alert_deliveries`（channel `email`、status `pending`）

### 通知文字（`app/modules/notifications/messages.py`）
- 標題：`{origin}→{destination} {M/D} {單程|來回}：{主要原因}`，主要原因文字：跌破目標價／歷史新低／低於典型價格
- 內文：`目前最低價 NT${price:,}（目標價 NT${target:,}）。` + 其他原因（例如「同時是歷史新低。」）
- `link`：`/watches/{watch.public_id}`
- 例：`TPE→NRT 12/19 來回：跌破目標價`／`目前最低價 NT$9,500（目標價 NT$10,000）。同時是歷史新低。`

## 寄信（`app/modules/notifications/email.py`）
```python
@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str

class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...   # 失敗拋 EmailError

class EmailError(Exception): ...
```

| 實作 | 說明 |
|---|---|
| `ConsoleEmailSender` | 用 logger 印出收件人、主旨、內文，不寄出 |
| `SmtpEmailSender` | 標準函式庫 `smtplib.SMTP` + `starttls()` + `login()` + `send_message()`，以 `asyncio.to_thread` 執行；逾時 30 秒；`smtplib.SMTPException`、`OSError` 轉成 `EmailError`，訊息先把密碼換成 `***` |

`get_email_sender(settings) -> EmailSender` 依設定選擇。

### 設定
| 變數 | 預設 | 說明 |
|---|---|---|
| `EMAIL_SENDER` | `console` | `console` 或 `smtp` |
| `SMTP_HOST` | 無 | Resend：`smtp.resend.com` |
| `SMTP_PORT` | `587` | STARTTLS |
| `SMTP_USERNAME` | 無 | Resend 固定為 `resend` |
| `SMTP_PASSWORD` | 無 | `SecretStr`；Resend 為 API key |
| `EMAIL_FROM` | 無 | 例如 `FareWatch <alert@網域>` |
| `APP_BASE_URL` | `http://localhost:5173` | 信中「查看追蹤」連結的開頭 |

`EMAIL_SENDER=smtp` 時 `SMTP_HOST`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`EMAIL_FROM` 缺一就啟動失敗（同 `SERPAPI_KEY` 的驗證方式）。

### 信件內容（純文字）
- 主旨 = 站內通知標題
- 內文 = 站內通知內文 + 空行 + `訂票：{booking_url}`（快照沒有連結就省略這行）+ `查看追蹤：{APP_BASE_URL}{link}` + 空行 + `可在設定頁關閉 Email 通知。`

## notifier（`app/modules/notifications/notifier.py`）
```python
MAX_ATTEMPTS = 5

async def send_pending(session, sender: EmailSender, settings) -> SendSummary  # sent、failed、skipped、retry
```

重複以下步驟直到沒有可處理的紀錄：
1. `SELECT ... FROM alert_deliveries WHERE status = 'pending' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED`，一併取得 alert、通知、快照、使用者
2. 使用者的 `email_enabled` 已關閉 → `skipped`，commit
3. 寄出成功 → `sent`、`sent_at = now`、`attempts + 1`
4. `EmailError` → `attempts + 1`、`last_error = 遮罩後的訊息`；`attempts >= MAX_ATTEMPTS` → `failed` 並 log error，否則維持 `pending`（下次執行再試）
5. 每筆各自 commit

為了避免同一次執行一直撞同一筆失敗的紀錄，一次執行內失敗過的 id 不再處理（查詢加 `id NOT IN (...)`）。

### 執行時機
- `python -m app.jobs.check_prices`：查價完成後呼叫一次 `send_pending`，摘要多印「寄出 N 封」
- `python -m app.jobs.send_notifications`：單獨補寄
- #7：由 SQS 或排程呼叫

## 系統通知（`app/modules/notifications/service.py`）
```python
async def create_system_notification(session, user_id, title, body, link=None, dedupe_key=None) -> None
```
`dedupe_key` 不是 NULL 時用 `INSERT ... ON CONFLICT DO NOTHING`。只 flush，由呼叫端 commit。

| 情境 | 實作 |
|---|---|
| 排隊中的追蹤被啟用 | `slots.rebalance` 改成回傳被啟用的 watch id 清單（`_activate_queued` 已經用 `RETURNING`）；`rebalance` 內對每個追蹤發「`{航線} {M/D} 已開始查價`」，`link = /watches/{public_id}`；`expire_watches` 與維護指令改用清單長度 |
| 本月額度用完 | `run_checks` 在 `remaining == 0` 時，對「`due_queries` 結果底下有 `active` 追蹤」的使用者發「本月查價額度已用完，下個月 1 號恢復」，`dedupe_key = quota_exhausted:{YYYY-MM}`（台灣時間），commit；log 照舊留 warning |

## 編輯追蹤後重置
`update_watch` 中，查價條件的值改變（`new != old`）或 `target_price` 的值改變時，刪除該追蹤的 `watch_alert_states`。只改 `status` 不重置。

## 通知 API（`app/modules/notifications/router.py`）
需登入；寫入用 `require_writable_user`（示範帳號 403）。

| 端點 | 說明 |
|---|---|
| `GET /notifications?unread_only=false&limit=20&before=` | 依 `created_at DESC, id DESC`；`limit` 1～100；`before` 是上一頁最後一則的 public_id（找不到或屬於別人 → 422）。回應 `{items: [...], unread_count}`；每則含 `id`（public_id）、`type`、`title`、`body`、`link`、`booking_url`（價格通知且快照有連結時）、`is_read`、`created_at` |
| `PATCH /notifications/{public_id}/read` | 標成已讀，回傳該則；別人的或不存在 → 404 |
| `POST /notifications/read-all` | 全部標成已讀，回 204 |
| `GET /me/notification-settings` | `{email_enabled}` |
| `PATCH /me/notification-settings` | 傳 `{email_enabled}`，upsert 後回傳 |

## 示範資料
`app.seeds.demo` 新增 `ensure_demo_notifications`（示範帳號已有任何通知就跳過）：
- 對「進行中」與「已過期」兩個示範追蹤，依時間順序把既有的示範快照逐筆餵給 `evaluate`（基準用 mock insights 模擬逐筆累積），符合條件的就建 `alerts` 與價格通知，`created_at` = 快照時間；最後寫入 `watch_alert_states`。示範價格由日期決定，所以每次 seed 產生的通知數量可能不同
- 1 則系統通知「TPE→NRT {M/D} 已開始查價」，時間為最早一筆示範快照前一天
- 最新一則價格通知未讀，其餘已讀
- 不建寄送紀錄（示範帳號不寄信）

## 測試
| 範圍 | 案例 |
|---|---|
| 觸發規則 | US-06 四個驗收情境依序（目標 10,000：9,500 通知 → 9,300 不通知 → 8,900 通知 → 10,500 不通知且重置 → 9,800 通知）；從未通知過的歷史新低直接通知；`history_ready_before` 為 false 時不算歷史新低；跟併入前的 `record_low` 比；跌破典型區間的狀態變化；多個原因合併、主要原因的優先順序；5% 門檻邊界（剛好 95% 通知、多 1 元不通知） |
| 通知文字 | 單程／來回、主要原因與其他原因的組合 |
| 套用規則（DB） | checker 跑完產生 alert、價格通知、pending 寄送紀錄；同一筆快照重跑不重複；暫停中的追蹤不通知；Email 關閉時不建寄送紀錄；查不到航班不判斷；同一 query 多個追蹤各自判斷 |
| 系統通知 | 補位啟用時主人收到通知；額度用完時受影響的使用者收到一次、同月再跑不重複、沒有 active 追蹤的使用者不會收到 |
| 編輯重置 | 改目標價、改條件 → 狀態被刪；只暫停／恢復 → 保留；送回相同值 → 保留 |
| notifier | 用假寄信器：成功 → `sent`；失敗 → 留 `pending`、`attempts + 1`、記錯誤；第 5 次失敗 → `failed`；寄出前關閉 Email → `skipped`；同一次執行不重撞失敗的紀錄；信件內容含訂票與查看追蹤連結 |
| 寄信器 | 設定驗證（smtp 缺欄位 → 錯誤）；SMTP 寄信器以 mock 的 `smtplib.SMTP` 確認 starttls、login、寄出的內容；例外轉 `EmailError` 且訊息不含密碼 |
| 通知 API | 排序與 `before` 分頁、`unread_only`、`unread_count`；別人的通知 → 404；read-all；設定讀寫與預設值；示範帳號寫入 → 403、讀取正常 |
| 示範 seed | 產生的通知與逐筆套用規則的結果一致；有 1 則系統通知；重跑不重複 |
| 入口 | `app.jobs.send_notifications` 加進 `tests/test_entrypoints.py`；新 model 加進 `app/db/models.py` |

## 文件更新（同一個分支）
- `docs/02-design.md`：架構與時序圖改為「checker 寫入 alerts、站內通知與待寄紀錄；notifier 只寄外部管道」；〈技術選型〉Email 改為 SMTP（Resend）；〈資料模型〉更新五張表的欄位
- `docs/architecture.md`：新增〈2026-10-24 #5 決策紀錄〉，記錄上方〈設計決定〉；架構圖的 SES 改為「Email（SMTP，Resend）」
- `docs/01-requirements.md`：〈網域與 Email〉改為 Resend；US-02 驗收條件的「系統通知於 M1 #5 補上」拿掉
- `docs/06-operations.md`：事件處理手冊新增「Email 寄不出去」：查 `alert_deliveries` 的 `failed` 與 `last_error` → 檢查 Resend 主控台與 DNS 記錄 → 修好後把 `failed` 改回 `pending` 並重設 `attempts`，再執行 `send_notifications`
