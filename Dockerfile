FROM python:3.12-slim

WORKDIR /app

COPY . /app

RUN pip install flask requests

ENV FLASK_APP=main.py

CMD ["flask", "run", "--host=0.0.0.0", "--port=5100"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD curl -f http://192.168.1.137:5100/api?t=movie&id=tt1375666 || exit 1
