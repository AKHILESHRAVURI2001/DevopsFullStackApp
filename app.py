import os
import time
import pymysql
import boto3
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "devsecret")

# =============================
# DATABASE CONFIG
# =============================
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_DB = os.getenv("MYSQL_DB", "appdb")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

# =============================
# STORAGE CONFIG
# =============================
USE_S3 = os.getenv("USE_S3", "false").lower() in ("1", "true", "yes")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET = os.getenv("S3_BUCKET")
LOCAL_UPLOAD_DIR = os.getenv("LOCAL_UPLOAD_DIR", "uploads")

if not USE_S3:
    os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
else:
    s3 = boto3.client("s3", region_name=AWS_REGION)


def get_db_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


def ensure_db():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            content TEXT,
            filename VARCHAR(255),
            storage_path VARCHAR(512),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
    conn.close()


@app.route('/')
def index():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM documents ORDER BY created_at DESC")
        docs = cur.fetchall()
    conn.close()
    return render_template('index.html', docs=docs)


@app.route('/create', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO documents (title, content) VALUES (%s, %s)", (title, content))
        conn.close()
        flash("Document created successfully!", "success")
        return redirect(url_for('index'))
    return render_template('create.html')


@app.route('/edit/<int:doc_id>', methods=['GET', 'POST'])
def edit(doc_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        if request.method == 'POST':
            title = request.form['title']
            content = request.form['content']
            cur.execute("UPDATE documents SET title=%s, content=%s WHERE id=%s", (title, content, doc_id))
            flash("Updated successfully!", "success")
            return redirect(url_for('index'))
        else:
            cur.execute("SELECT * FROM documents WHERE id=%s", (doc_id,))
            doc = cur.fetchone()
    conn.close()

    if not doc:
        flash("Document not found", "danger")
        return redirect(url_for('index'))

    return render_template('edit.html', doc=doc)


@app.route('/upload/<int:doc_id>', methods=['GET', 'POST'])
def upload(doc_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM documents WHERE id=%s", (doc_id,))
        doc = cur.fetchone()
    conn.close()

    if not doc:
        flash("Document not found", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        file = request.files['file']
        if not file or file.filename == '':
            flash("No file selected", "danger")
            return redirect(request.url)

        filename = file.filename
        timestamp = int(time.time())

        if USE_S3:
            key = f"documents/{doc_id}/{timestamp}_{filename}"
            s3.upload_fileobj(file, S3_BUCKET, key)
            storage_path = key
        else:
            save_path = os.path.join(LOCAL_UPLOAD_DIR, f"{timestamp}_{filename}")
            file.save(save_path)
            storage_path = save_path

        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("UPDATE documents SET filename=%s, storage_path=%s WHERE id=%s", (filename, storage_path, doc_id))
        conn.close()
        flash("File uploaded successfully!", "success")
        return redirect(url_for('index'))

    return render_template('upload.html', doc=doc)


@app.route('/delete/<int:doc_id>', methods=['POST'])
def delete(doc_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT storage_path FROM documents WHERE id=%s", (doc_id,))
        row = cur.fetchone()
        if row and row.get("storage_path"):
            if USE_S3:
                s3.delete_object(Bucket=S3_BUCKET, Key=row["storage_path"])
            else:
                try:
                    os.remove(row["storage_path"])
                except Exception as e:
                    print("Failed to delete local file:", e)
        cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
    conn.close()
    flash("Document deleted successfully!", "success")
    return redirect(url_for('index'))


@app.route('/files/<int:doc_id>')
def file_link(doc_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT filename, storage_path FROM documents WHERE id=%s", (doc_id,))
        doc = cur.fetchone()
    conn.close()

    if not doc or not doc['storage_path']:
        flash("No file available", "danger")
        return redirect(url_for('index'))

    if USE_S3:
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': doc['storage_path']},
            ExpiresIn=300
        )
        return redirect(url)
    else:
        return send_from_directory('.', doc['storage_path'], as_attachment=True)


if __name__ == '__main__':
    ensure_db()
    app.run(debug=True)
