FROM python:3.11-slim

WORKDIR /app

COPY idea/tiktok-live/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY idea/tiktok-live/ /app/

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "run:app"]
