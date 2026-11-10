
import os
import re
import cv2
import time
import base64
import numpy as np
import psycopg2

try:
    import winsound
except ImportError:
    winsound = None

from datetime import datetime, date
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify,
    url_for, flash, session, redirect
)
from dotenv import load_dotenv


# =====================================================
# CONFIGURATION
# =====================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

app = Flask(__name__, template_folder="template")

app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is missing from .env")


# =====================================================
# DATABASE CONFIGURATION
# =====================================================

DB_SETTINGS = {
    "dbname": "students",
    "user": "postgres",
    "password": os.getenv("DB_PASSWORD"),
    "host": "localhost",
    "port": "5432"
}

if not DB_SETTINGS["password"]:
    raise RuntimeError("DB_PASSWORD is missing from .env")


def get_db_connection():
    return psycopg2.connect(**DB_SETTINGS)


# =====================================================
# ADMIN CONFIGURATION
# =====================================================

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise RuntimeError("Admin credentials are missing from .env")


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please login as admin first.", "warning")
            return redirect(url_for("admin_login"))

        return function(*args, **kwargs)

    return wrapper


# =====================================================
# IMAGE DIRECTORY
# =====================================================

CAPTURED_IMAGES_DIR = os.path.join(
    BASE_DIR, "captured_images"
)

os.makedirs(CAPTURED_IMAGES_DIR, exist_ok=True)


# =====================================================
# FACE DETECTION
# =====================================================

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades +
    "haarcascade_frontalface_default.xml"
)

if face_cascade.empty():
    raise RuntimeError("Could not load face detection classifier.")


def beep():
    if winsound:
        try:
            winsound.Beep(1000, 500)
        except RuntimeError:
            pass


def normalize_face(face):
    face = cv2.resize(face, (100, 100))
    face = cv2.equalizeHist(face)
    return face


def safe_folder_name(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.strip().replace(" ", "_")


def parse_validity(value):
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        return datetime.strptime(
            value.strip().split()[0],
            "%Y-%m-%d"
        ).date()

    return None


# =====================================================
# HOME
# =====================================================

@app.route("/")
def home():
    return render_template("home.html")


# =====================================================
# ADMIN LOGIN
# =====================================================

@app.route(
    "/template/admin/login.html",
    methods=["GET", "POST"]
)
def admin_login():

    error_message = None

    if request.method == "POST":

        username = request.form.get(
            "username", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        if (
            username == ADMIN_USERNAME.strip()
            and password == ADMIN_PASSWORD
        ):

            session.clear()
            session["admin_logged_in"] = True

            return redirect(url_for("admin_dashboard"))

        error_message = "Invalid credentials. Please try again."

    return render_template(
        "admin/login.html",
        error_message=error_message
    )


# =====================================================
# ADMIN DASHBOARD
# =====================================================

@app.route(
    "/template/admin/dashboard.html",
    methods=["GET", "POST"]
)
@admin_required
def admin_dashboard():

    users = []
    today = date.today()

    conn = None
    cursor = None

    try:

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id,
                full_name,
                contact_number,
                address,
                arrival_stop,
                destination_stop,
                bus_pass_validity
            FROM student_registration
            ORDER BY id DESC
        """)

        rows = cursor.fetchall()

        for row in rows:

            (
                user_id,
                full_name,
                contact,
                address,
                arrival,
                destination,
                validity
            ) = row

            validity_date = parse_validity(validity)

            users.append({
                "id": user_id,
                "name": full_name,
                "contact": contact,
                "address": address,
                "arrival": arrival,
                "destination": destination,
                "validity": validity,
                "is_expired": (
                    validity_date is not None
                    and validity_date < today
                )
            })

    except Exception as e:

        print("Dashboard error:", e)

        flash(
            "Unable to load student records. Check database connection and table columns.",
            "danger"
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    return render_template(
        "admin/dashboard.html",
        users=users
    )


# =====================================================
# ADD STUDENT
# =====================================================

@app.route("/admin/users/add", methods=["POST"])
@admin_required
def add_user():

    conn = None
    cursor = None

    try:

        full_name = request.form.get("fullName", "").strip()
        contact_number = request.form.get("contactNumber", "").strip()
        address = request.form.get("address", "").strip()
        arrival_stop = request.form.get("arrivalStop", "").strip()
        destination_stop = request.form.get("destinationStop", "").strip()
        validity = request.form.get("busPassValidity", "").strip()

        if not all([
            full_name,
            contact_number,
            address,
            arrival_stop,
            destination_stop,
            validity
        ]):
            flash("Please fill all student details.", "warning")
            return redirect(url_for("admin_dashboard"))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO student_registration (
                full_name,
                contact_number,
                address,
                arrival_stop,
                destination_stop,
                bus_pass_validity
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            full_name,
            contact_number,
            address,
            arrival_stop,
            destination_stop,
            validity
        ))

        conn.commit()

        flash("Student added successfully.", "success")

    except Exception as e:

        if conn:
            conn.rollback()

        print("Add student error:", e)
        flash("Unable to add student.", "danger")

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    return redirect(url_for("admin_dashboard"))


# =====================================================
# UPDATE STUDENT
# =====================================================

@app.route(
    "/admin/users/update/<int:user_id>",
    methods=["POST"]
)
@admin_required
def update_user(user_id):

    conn = None
    cursor = None

    try:

        full_name = request.form.get("fullName", "").strip()
        contact_number = request.form.get("contactNumber", "").strip()
        address = request.form.get("address", "").strip()
        arrival_stop = request.form.get("arrivalStop", "").strip()
        destination_stop = request.form.get("destinationStop", "").strip()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE student_registration
            SET
                full_name = %s,
                contact_number = %s,
                address = %s,
                arrival_stop = %s,
                destination_stop = %s
            WHERE id = %s
        """, (
            full_name,
            contact_number,
            address,
            arrival_stop,
            destination_stop,
            user_id
        ))

        conn.commit()

        flash("Student updated successfully.", "success")

    except Exception as e:

        if conn:
            conn.rollback()

        print("Update student error:", e)
        flash("Unable to update student.", "danger")

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    return redirect(url_for("admin_dashboard"))


# =====================================================
# DELETE STUDENT
# =====================================================

@app.route(
    "/admin/users/delete/<int:user_id>",
    methods=["POST"]
)
@admin_required
def delete_user(user_id):

    conn = None
    cursor = None

    try:

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM student_registration
            WHERE id = %s
        """, (user_id,))

        conn.commit()

        flash("Student deleted successfully.", "success")

    except Exception as e:

        if conn:
            conn.rollback()

        print("Delete student error:", e)
        flash("Unable to delete student.", "danger")

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    return redirect(url_for("admin_dashboard"))


# =====================================================
# ADMIN LOGOUT
# =====================================================

@app.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully.", "info")

    return redirect(url_for("admin_login"))


# =====================================================
# STUDENT PAGES
# =====================================================

@app.route("/template/student/start.html")
def student_start():
    return render_template("student/start.html")


@app.route("/template/student/register.html")
def student_register():
    return render_template("student/register.html")


# =====================================================
# FACE RECOGNIZER TRAINING
# =====================================================

def train_recognizer():

    if not hasattr(cv2, "face"):
        raise RuntimeError(
            "OpenCV face module is missing. Install opencv-contrib-python."
        )

    recognizer = cv2.face.LBPHFaceRecognizer_create()

    faces = []
    labels = []
    label_names = {}

    label_number = 0

    for folder in sorted(os.listdir(CAPTURED_IMAGES_DIR)):

        folder_path = os.path.join(
            CAPTURED_IMAGES_DIR,
            folder
        )

        if not os.path.isdir(folder_path):
            continue

        label_names[label_number] = folder.replace(
            "_", " "
        )

        for filename in os.listdir(folder_path):

            if not filename.lower().endswith(
                (".jpg", ".jpeg", ".png")
            ):
                continue

            image_path = os.path.join(
                folder_path,
                filename
            )

            image = cv2.imread(
                image_path,
                cv2.IMREAD_GRAYSCALE
            )

            if image is None:
                continue

            faces.append(normalize_face(image))
            labels.append(label_number)

        label_number += 1

    if not faces:
        raise ValueError("No registered face images found.")

    recognizer.train(
        faces,
        np.array(labels, dtype=np.int32)
    )

    return recognizer, label_names


# =====================================================
# STUDENT FACE VERIFICATION
# =====================================================

@app.route(
    "/template/student/verification.html",
    methods=["GET", "POST"]
)
def student_verification():

    if request.method == "GET":
        return render_template("student/verification.html")

    conn = None
    cursor = None

    try:

        data = request.get_json(silent=True) or {}
        image_data = data.get("image", "")

        if "," not in image_data:
            return jsonify({
                "verified": False,
                "message": "Please capture an image."
            }), 400

        encoded_image = image_data.split(",", 1)[1]

        image_bytes = base64.b64decode(
            encoded_image,
            validate=True
        )

        image_array = np.frombuffer(
            image_bytes,
            dtype=np.uint8
        )

        image = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR
        )

        if image is None:
            return jsonify({
                "verified": False,
                "message": "Invalid captured image."
            }), 400

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY
        )

        detected_faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(50, 50)
        )

        if len(detected_faces) == 0:
            return jsonify({
                "verified": False,
                "message": "Face not detected. Please try again."
            })

        recognizer, label_names = train_recognizer()

        for (x, y, w, h) in detected_faces:

            face = gray[y:y + h, x:x + w]
            face = normalize_face(face)

            label, confidence = recognizer.predict(face)

            if confidence > 80:
                beep()

                return jsonify({
                    "verified": False,
                    "message": "Face not recognized."
                })

            student_name = label_names.get(label)

            if not student_name:
                continue

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT bus_pass_validity
                FROM student_registration
                WHERE LOWER(TRIM(REPLACE(full_name, ' ', '_'))) = LOWER(%s)
                LIMIT 1
            """, (student_name.replace(" ", "_"),))

            result = cursor.fetchone()

            cursor.close()
            cursor = None

            conn.close()
            conn = None

            if not result:
                beep()

                return jsonify({
                    "verified": False,
                    "message": "Student record not found."
                })

            validity_date = parse_validity(result[0])

            if validity_date is None:
                return jsonify({
                    "verified": False,
                    "message": "Invalid bus pass validity date."
                })

            if validity_date >= date.today():

                return jsonify({
                    "verified": True,
                    "message": (
                        f"Welcome {student_name}. "
                        f"Your bus pass is valid until {validity_date}."
                    )
                })

            beep()

            return jsonify({
                "verified": False,
                "message": (
                    f"Your bus pass expired on {validity_date}. "
                    "Please renew your pass."
                )
            })

        return jsonify({
            "verified": False,
            "message": "Face verification failed."
        })

    except Exception as e:

        print("Face verification error:", e)

        return jsonify({
            "verified": False,
            "message": "An error occurred during face verification."
        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# =====================================================
# STUDENT REGISTRATION AND WEBCAM CAPTURE
# =====================================================

@app.route("/capture", methods=["POST"])
def capture_images():

    import json
    import base64

    conn = None
    cursor = None
    saved_paths = []

    try:
        full_name = request.form.get("fullName", "").strip()
        contact_number = request.form.get("contactNumber", "").strip()
        address = request.form.get("address", "").strip()
        arrival_stop = request.form.get("arrivalStop", "").strip()
        destination_stop = request.form.get("destinationStop", "").strip()
        validity = request.form.get("busPassValidity", "").strip()

        receipt = request.files.get("paymentReceipt")

        # Validate registration fields
        if not all([
            full_name,
            contact_number,
            address,
            arrival_stop,
            destination_stop,
            validity
        ]):
            return jsonify({
                "error": "Please complete all fields."
            }), 400

        if not re.fullmatch(r"[0-9]{10}", contact_number):
            return jsonify({
                "error": "Enter a valid 10-digit contact number."
            }), 400

        if not receipt or not receipt.filename:
            return jsonify({
                "error": "Please upload payment receipt."
            }), 400

        if not receipt.filename.lower().endswith(".pdf"):
            return jsonify({
                "error": "Receipt must be a PDF file."
            }), 400

        receipt_data = receipt.read()

        if not receipt_data:
            return jsonify({
                "error": "Uploaded receipt is empty."
            }), 400

        # Receive 10 images from browser
        images_json = request.form.get("faceImages", "")

        try:
            face_images = json.loads(images_json)
        except (ValueError, TypeError):
            return jsonify({
                "error": "Invalid face image data."
            }), 400

        if not isinstance(face_images, list) or len(face_images) != 10:
            return jsonify({
                "error": "Exactly 10 face images are required."
            }), 400

        # Decode and validate images before saving
        decoded_images = []

        for image_data in face_images:

            if not isinstance(image_data, str) or "," not in image_data:
                return jsonify({
                    "error": "Invalid captured image."
                }), 400

            header, encoded_image = image_data.split(",", 1)

            if "image/jpeg" not in header:
                return jsonify({
                    "error": "Only JPEG images are accepted."
                }), 400

            image_bytes = base64.b64decode(
                encoded_image,
                validate=True
            )

            image_array = np.frombuffer(
                image_bytes,
                dtype=np.uint8
            )

            image = cv2.imdecode(
                image_array,
                cv2.IMREAD_GRAYSCALE
            )

            if image is None:
                return jsonify({
                    "error": "Unable to read captured face image."
                }), 400

            decoded_images.append(image)

        # Create student image folder
        folder_name = safe_folder_name(full_name)

        user_folder = os.path.join(
            CAPTURED_IMAGES_DIR,
            folder_name
        )

        os.makedirs(user_folder, exist_ok=True)

        # Save all 10 images
        for index, image in enumerate(decoded_images):

            image_path = os.path.join(
                user_folder,
                f"image_{index + 1}.jpg"
            )

            if not cv2.imwrite(image_path, image):
                raise IOError("Unable to save face image.")

            saved_paths.append(image_path)

        # Connect to PostgreSQL
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO student_registration (
                full_name,
                contact_number,
                address,
                arrival_stop,
                destination_stop,
                bus_pass_validity,
                payment_receipt
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            full_name,
            contact_number,
            address,
            arrival_stop,
            destination_stop,
            validity,
            psycopg2.Binary(receipt_data)
        ))

        conn.commit()

        return jsonify({
            "message": "Registration successful! 10 face images captured.",
            "images_captured": len(saved_paths)
        }), 200

    except Exception as e:

        if conn:
            conn.rollback()

        # Remove newly saved images if registration fails
        for image_path in saved_paths:
            if os.path.exists(image_path):
                os.remove(image_path)

        app.logger.exception("Student registration failed")

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    try:

        full_name = request.form.get("fullName", "").strip()
        contact_number = request.form.get("contactNumber", "").strip()
        address = request.form.get("address", "").strip()
        arrival_stop = request.form.get("arrivalStop", "").strip()
        destination_stop = request.form.get("destinationStop", "").strip()
        validity = request.form.get("busPassValidity", "").strip()

        receipt = request.files.get("paymentReceipt")

        if not all([
            full_name,
            contact_number,
            address,
            arrival_stop,
            destination_stop,
            validity
        ]) or not receipt or not receipt.filename:

            return jsonify({
                "error": "Please complete all fields and upload payment receipt."
            }), 400

        receipt_data = receipt.read()

        if not receipt_data:
            return jsonify({
                "error": "Uploaded payment receipt is empty."
            }), 400

        camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)

        if not camera.isOpened():
         camera.release()
         return jsonify({
        "error": "Camera initialization failed. Please check webcam permissions."
    }), 500

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO student_registration (
                full_name,
                contact_number,
                address,
                arrival_stop,
                destination_stop,
                bus_pass_validity,
                payment_receipt
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            full_name,
            contact_number,
            address,
            arrival_stop,
            destination_stop,
            validity,
            psycopg2.Binary(receipt_data)
        ))

        conn.commit()

        cursor.close()
        cursor = None

        conn.close()
        conn = None

        folder_name = safe_folder_name(full_name)

        user_folder = os.path.join(
            CAPTURED_IMAGES_DIR,
            folder_name
        )

        os.makedirs(
            user_folder,
            exist_ok=True
        )

        image_count = 0
        maximum_images = 20

        instructions = [
            "Look straight at the camera",
            "Turn slightly left",
            "Turn slightly right",
            "Look slightly up",
            "Look slightly down",
            "Keep a neutral expression",
            "Smile slightly",
            "Blink naturally",
            "Look straight again",
            "Keep your face steady"
        ]

        for instruction in instructions:

            print("Instruction:", instruction)

            time.sleep(1)

            for _ in range(3):

                success, frame = camera.read()

                if not success:
                    continue

                gray = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2GRAY
                )

                detected_faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(50, 50)
                )

                if len(detected_faces) == 0:
                    continue

                x, y, w, h = max(
                    detected_faces,
                    key=lambda box: box[2] * box[3]
                )

                face = gray[y:y + h, x:x + w]
                face = normalize_face(face)

                image_count += 1

                image_path = os.path.join(
                    user_folder,
                    f"image_{image_count}.jpg"
                )

                cv2.imwrite(image_path, face)

                if image_count >= maximum_images:
                    break

            if image_count >= maximum_images:
                break

        if image_count == 0:

            return jsonify({
                "error": (
                    "No face images captured. "
                    "Please check lighting and camera position."
                )
            }), 400

        return jsonify({
            "message": (
                f"Registration successful. "
                f"{image_count} face images captured for {full_name}."
            ),
            "images_captured": image_count
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print("Registration error:", e)

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

        if camera:
            camera.release()


# =====================================================
# RUN APPLICATION
# =====================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
