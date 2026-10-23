"""載入所有 model，讓 Base.metadata 包含每張表。

外鍵是用表名字串指定的，被指向的表也要已註冊才能解析；
所以 Alembic 和每個獨立執行的指令（seed、維護）都要 import 這個模組。
"""

from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.prices import models as prices_models  # noqa: F401
from app.modules.reference import models as reference_models  # noqa: F401
from app.modules.users import models as users_models  # noqa: F401
from app.modules.watches import models as watches_models  # noqa: F401
