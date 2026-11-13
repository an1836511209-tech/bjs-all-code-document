FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY scripts/dmp_mock /app/scripts/dmp_mock
USER 10003:10003
EXPOSE 8025
ENTRYPOINT ["python", "-m", "scripts.dmp_mock.server"]
CMD ["--host", "0.0.0.0", "--environment", "test"]
