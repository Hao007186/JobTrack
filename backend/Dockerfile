# 同一份 image：Lambda（arm64）用基底預設的 Lambda runtime 進入點；
# 本機 compose、k8s（amd64）覆寫 entrypoint 改跑 uvicorn。見 docs/02-design.md〈容器執行方式〉
FROM ghcr.io/astral-sh/uv:0.12.17 AS uv

FROM public.ecr.aws/lambda/python:3.14

COPY --from=uv /uv /bin/uv

ENV PYTHONPATH=${LAMBDA_TASK_ROOT} \
    UV_NO_CACHE=1

WORKDIR ${LAMBDA_TASK_ROOT}

# 先只複製相依套件清單，程式碼變動時不必重裝套件
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
    && uv pip install --system --target ${LAMBDA_TASK_ROOT} -r requirements.txt \
    && rm requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Lambda handler 在 M1 子專案 #7（部署）加入
