FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static

# Run as a non-root user; /srv/data holds the SQLite file (later milestones).
RUN useradd --create-home jigyasa && mkdir -p /srv/data && chown jigyasa /srv/data
USER jigyasa

EXPOSE 3000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
