Optional — Run local MinIO (like fake S3)

Download MinIO from https://min.io/download

./minio server /tmp/minio-data

Visit http://localhost:9000
 → login minioadmin / minioadmin.

Then .env → set USE_MINIO=true.