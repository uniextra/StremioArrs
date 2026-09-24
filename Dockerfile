FROM python:3.12-slim

WORKDIR /app

# Create unprivileged user and group
RUN groupadd -g 1000 stremioarrs && \
    useradd -u 1000 -g stremioarrs -s /bin/sh -d /app stremioarrs

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy source code with ownership assigned to the unprivileged user
COPY --chown=stremioarrs:stremioarrs . .

# Switch to non-root user
USER stremioarrs

EXPOSE 5100

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5100/api?t=caps')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5100", "--workers", "4", "--threads", "4", "--timeout", "60", "main:app"]
