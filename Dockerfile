FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data PATH=/app/.venv/bin:$PATH
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.10 && groupadd -g 10001 agent && useradd -u 10001 -g agent -m agent
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev && mkdir /data && chown -R agent:agent /data /app
USER 10001:10001
EXPOSE 8021
HEALTHCHECK --interval=15s --timeout=8s --start-period=20s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8021/health', timeout=5)"
CMD ["uvicorn", "issue_agent.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8021", "--log-level", "warning"]
