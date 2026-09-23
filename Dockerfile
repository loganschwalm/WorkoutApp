# The self-hosted server uses only Python standard-library modules.
FROM python:3.12-slim
RUN useradd --system --user-group --no-create-home --shell /usr/sbin/nologin workout
WORKDIR /app
COPY frontend /app/frontend
COPY backend/server.py /app/server.py
COPY docker-entrypoint.py /app/docker-entrypoint.py
RUN mkdir -p /app/data && chown workout:workout /app/data
ENV PORT=6769
ENV APP_ROOT=/app/frontend
ENV WORKOUT_DB=/app/data/workouts.db
EXPOSE 6769
# Starts as root only to hand /app/data to the workout user (a volume from an older, root-run image can be
# owned by root), then runs the server as that user. See docker-entrypoint.py.
ENTRYPOINT ["python", "/app/docker-entrypoint.py"]
CMD ["python", "/app/server.py"]
