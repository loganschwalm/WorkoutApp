FROM python:3.12-slim
WORKDIR /app
COPY frontend /app/frontend
COPY backend/server.py /app/server.py
RUN mkdir -p /app/data
ENV PORT=8000
ENV APP_ROOT=/app/frontend
ENV WORKOUT_DB=/app/data/workouts.db
EXPOSE 8000
CMD ["python", "server.py"]
