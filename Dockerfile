FROM python:3.12-slim
WORKDIR /app
COPY frontend /app/frontend
COPY backend/server.py /app/server.py
RUN mkdir -p /app/data
ENV PORT=8000
EXPOSE 8000
CMD ["python", "server.py"]
