FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY reviewer ./reviewer
RUN pip install --no-cache-dir .

RUN useradd --create-home reviewer
USER reviewer

EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/healthz')" || exit 1
CMD ["uvicorn", "reviewer.webhook:default_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
