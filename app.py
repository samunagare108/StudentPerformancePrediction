from flask import Flask
import csv
from flask import Flask, request, render_template, Response, session, redirect, url_for
import joblib
import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg
import json
# TEST_FROM_VSCODE
from werkzeug.security import generate_password_hash, check_password_hash
app = Flask(__name__)
load_dotenv(Path(__file__).resolve().parent / '.env')
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-development-key-change-before-deploy")

# Load trained ML model
model = joblib.load("model/student_performance_model.pkl")
with open("model/model_metrics.json", "r") as file:
    model_metrics = json.load(file)
@app.route("/")
def home():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]
        role = request.form["role"]

        conn = psycopg.connect(os.environ["DATABASE_URL"])
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, password, role
            FROM users
            WHERE username = %s AND role = %s
        """, (username, role))

        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user[2], password):

            session["user_id"] = user[0]
            session["username"] = user[1]
            session["role"] = user[3]

            if user[3] == "student":
                return redirect(url_for("student_dashboard"))

            elif user[3] == "teacher":
                return redirect(url_for("teacher_dashboard"))
        return render_template(
            "login.html",
            error="Invalid username, password or role."
        )

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        student_name = request.form.get("student_name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        role = request.form.get("role", "").strip()
        teacher_code = request.form.get("teacher_code", "")

        if not username or not password:
            return render_template("register.html", error="Please fill in all required fields.")

        if len(username) < 3 or len(password) < 8:
            return render_template(
                "register.html",
                error="Username must be at least 3 characters and password at least 8 characters."
            )

        if role not in ("student", "teacher"):
            return render_template("register.html", error="Please select a valid role.")

        if role == "student" and (not student_name or not student_id):
            return render_template(
                "register.html",
                error="Student name and registered Student ID are required."
            )

        if role == "teacher":
            expected_code = os.environ.get("TEACHER_REGISTRATION_CODE", "")
            if not expected_code or teacher_code != expected_code:
                return render_template(
                    "register.html",
                    error="Teacher registration code is invalid or not configured."
                )

        conn = psycopg.connect(os.environ["DATABASE_URL"])
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                conn.close()
                return render_template("register.html", error="That username is already registered.")

            if role == "student":
                cursor.execute("SELECT 1 FROM users WHERE student_id = %s", (student_id,))
                if cursor.fetchone():
                    conn.close()
                    return render_template("register.html", error="That Student ID is already registered.")

            cursor.execute(
                """
                INSERT INTO users (username, password, role, student_name, student_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    student_name if role == "student" else None,
                    student_id if role == "student" else None
                )
            )
            conn.commit()
        except psycopg.IntegrityError:
            conn.rollback()
            conn.close()
            return render_template("register.html", error="Username or Student ID is already in use.")
        except Exception:
            conn.rollback()
            conn.close()
            app.logger.exception("Registration failed")
            return render_template("register.html", error="Registration failed. Please try again.")
        else:
            conn.close()

        return render_template(
            "login.html",
            success="Registration successful. You can now log in."
        )

    return render_template("register.html")


@app.route("/predict-form")
def predict_form():

    if "user_id" not in session:
        return redirect(url_for("login"))



    return render_template("index.html")    

@app.route("/student-dashboard")
def student_dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "student":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT student_id
            FROM users
            WHERE id = %s
        """, (session["user_id"],))

        registered = cursor.fetchone()

        if not registered or not registered[0]:
            return "Registered Student ID not found."

        registered_student_id = registered[0].strip()

        cursor.execute("""
            SELECT student_name,
                   student_id,
                   predicted_score,
                   performance,
                   recommendation,
                   risk_level
            FROM predictions
            WHERE user_id = %s
              AND TRIM(student_id) = %s
            ORDER BY id DESC
            LIMIT 1
        """, (session["user_id"], registered_student_id))

        latest_prediction = cursor.fetchone()

    finally:
        conn.close()

    return render_template(
        "student_dashboard.html",
        username=session.get("username"),
        prediction=latest_prediction
    )
@app.route("/what-if", methods=["GET", "POST"])
def what_if():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "student":
        return "Only students can use What-If Analysis."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    # Get latest prediction and its input values
    cursor.execute("""
        SELECT
            predicted_score,
            study_hours,
            attendance,
            previous_score,
            assignments_completed,
            sleep_hours,
            participation
        FROM predictions
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT 1
    """, (session["user_id"],))

    latest = cursor.fetchone()

    conn.close()

    # If student has no previous prediction
    if not latest:
        return redirect(url_for("predict_form"))

    current_score = latest[0]

    if request.method == "GET":

        return render_template(
            "what_if.html",
            study_hours=latest[1],
            attendance=latest[2],
            previous_score=latest[3],
            assignments_completed=latest[4],
            total_assignments=10,
            sleep_hours=latest[5],
            participation=latest[6]
        )

    try:
        study_hours = float(request.form["study_hours"])
        attendance = float(request.form["attendance"])
        previous_score = float(request.form["previous_score"])
        total_assignments = int(request.form["total_assignments"])
        assignments_completed = int(request.form["assignments_completed"])
        sleep_hours = float(request.form["sleep_hours"])
        participation = int(request.form["participation"])

    except ValueError:
        return "Please enter valid values."

    # Server-side validation
    if not 1 <= study_hours <= 8:
        return "Study Hours must be between 1 and 8."

    if not 50 <= attendance <= 100:
        return "Attendance must be between 50 and 100."

    if not 40 <= previous_score <= 95:
        return "Previous Score must be between 40 and 95."

    if not 1 <= total_assignments <= 100:
        return "Total Assignments must be between 1 and 100."

    if not 0 <= assignments_completed <= total_assignments:
        return "Completed Assignments must be between 0 and Total Assignments."

    completion_rate = (assignments_completed / total_assignments) * 100
    assignment_model_score = completion_rate / 10

    if not 4 <= sleep_hours <= 9:
        return "Sleep Hours must be between 4 and 9."

    if not 0 <= participation <= 10:
        return "Participation must be between 0 and 10."

    # Predict new scenario
    prediction = model.predict([[
        study_hours,
        attendance,
        previous_score,
        assignment_model_score,
        sleep_hours,
        participation
    ]])

    predicted_score = round(prediction[0], 2)
    
    # Performance classification
    # Performance classification
    if predicted_score >= 85:
        performance = "Excellent"
    elif predicted_score >= 70:
        performance = "Good"
    elif predicted_score >= 50:
        performance = "Average"
    else:
        performance = "Poor"


# Personalized recommendation
    recommendations = []

    if attendance < 75:
        recommendations.append("Improve attendance to at least 75%.")

    if study_hours < 4:
        recommendations.append("Increase daily study hours.")

    if completion_rate < 70:
        recommendations.append("Complete more assignments regularly.")

    if participation < 5:
        recommendations.append("Increase classroom participation.")

    if sleep_hours < 6:
        recommendations.append("Maintain at least 6 hours of sleep.")

    if previous_score < 60:
        recommendations.append("Focus on strengthening your previous weak areas.")


    if recommendations:
        recommendation = " ".join(recommendations)
    else:
        recommendation = "Great work! Your academic habits are well balanced. Keep maintaining your consistency."

# Risk classification
    if predicted_score >= 85:
        risk_level = "Low Risk"
    elif predicted_score >= 70:
        risk_level = "Medium Risk"
    else:
        risk_level = "High Risk"

    improvement = round(predicted_score - current_score, 2)


    return render_template(
        "what_if_result.html",
            performance=performance,
    risk_level=risk_level,
    recommendation=recommendation,
        predicted_score=predicted_score,
        current_score=current_score,
        improvement=improvement,
        study_hours=study_hours,
        attendance=attendance,
        previous_score=previous_score,
        assignments_completed=assignments_completed,
        total_assignments=total_assignments,
        completion_rate=round(completion_rate, 1),
        sleep_hours=sleep_hours,
        participation=participation
    )
    
@app.route("/high-risk-students")
def high_risk_students():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            student_name,
            student_id,
            predicted_score,
            performance,
            risk_level
        FROM predictions
        WHERE risk_level = 'High Risk'
          AND NOT (
              student_name = student_id
              AND (
                  student_id ~ '^S[0-9]{3}$'
                  OR student_id = 'S1000'
              )
          )
          AND id IN (
              SELECT MAX(id)
              FROM predictions
              GROUP BY student_id
          )
        ORDER BY predicted_score ASC
    """)

    students = cursor.fetchall()
    conn.close()

    return render_template(
        "high_risk_students.html",
        students=students
    )
    


@app.route("/student-analytics/<student_id>")
def student_analytics(student_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    # Complete prediction history
    cursor.execute("""
        SELECT
            student_name,
            student_id,
            predicted_score,
            performance,
            risk_level,
            study_hours,
            attendance,
            previous_score,
            assignments_completed,
            sleep_hours,
            participation,
            prediction_date
        FROM predictions
        WHERE student_id = %s
        ORDER BY prediction_date DESC
    """, (student_id,))

    predictions = cursor.fetchall()

    if not predictions:
        conn.close()
        return "No prediction history found for this Student ID."

    student_name = predictions[0][0]

    # Week-wise average performance
    cursor.execute("""
        SELECT
            to_char(prediction_date::timestamp, 'IYYY-"W"IW') AS period,
            ROUND(AVG(predicted_score)::numeric, 2) AS average_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        GROUP BY period
        ORDER BY period
    """, (student_id,))

    weekly_data = cursor.fetchall()

    # Month-wise average performance
    cursor.execute("""
        SELECT
            to_char(prediction_date::timestamp, 'YYYY-MM') AS period,
            ROUND(AVG(predicted_score)::numeric, 2) AS average_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        GROUP BY period
        ORDER BY period
    """, (student_id,))

    monthly_data = cursor.fetchall()

    # Year-wise average performance
    cursor.execute("""
        SELECT
            to_char(prediction_date::timestamp, 'YYYY') AS period,
            ROUND(AVG(predicted_score)::numeric, 2) AS average_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        GROUP BY period
        ORDER BY period
    """, (student_id,))

    yearly_data = cursor.fetchall()
        # Individual dated predictions for performance trend
    cursor.execute("""
        SELECT
            prediction_date,
            predicted_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        ORDER BY prediction_date
    """, (student_id,))

    prediction_points = cursor.fetchall()
    conn.close()

    return render_template(
        "student_analytics.html",
        student_name=student_name,
        student_id=student_id,
        predictions=predictions,
        weekly_data=weekly_data,
        monthly_data=monthly_data,
        yearly_data=yearly_data,
        prediction_points=prediction_points
    )


@app.route("/all-students")
def all_students():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    search = request.args.get("search", "").strip()

    students_per_page = 20

    base_query = """
        SELECT student_name,
               student_id,
               predicted_score,
               performance,
               risk_level
        FROM predictions
        WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        )
        AND id IN (
            SELECT MAX(id)
            FROM predictions
            WHERE NOT (
                student_name = student_id
                AND (
                    student_id ~ '^S[0-9]{3}$'
                    OR student_id = 'S1000'
                )
            )
            GROUP BY student_id
        )
    """

    if search:
        base_query += """
            AND (
                student_name LIKE %s
                OR student_id LIKE %s
            )
        """

        search_value = f"%{search}%"

        cursor.execute(
            "SELECT COUNT(*) FROM (" + base_query + ")",
            (search_value, search_value)
        )

        filtered_total = cursor.fetchone()[0]

        total_pages = max(
            1,
            (filtered_total + students_per_page - 1) // students_per_page
        )

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * students_per_page

        base_query += """
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """

        cursor.execute(
            base_query,
            (search_value, search_value, students_per_page, offset)
        )

    else:
        cursor.execute(
            "SELECT COUNT(*) FROM (" + base_query + ")"
        )

        filtered_total = cursor.fetchone()[0]

        total_pages = max(
            1,
            (filtered_total + students_per_page - 1) // students_per_page
        )

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * students_per_page

        base_query += """
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """

        cursor.execute(
            base_query,
            (students_per_page, offset)
        )

    students = cursor.fetchall()

    conn.close()

    return render_template(
        "all_students.html",
        students=students,
        page=page,
        total_pages=total_pages,
        search=search
    )


@app.route("/teacher-dashboard")
def teacher_dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    # Total unique students
    cursor.execute("""SELECT COUNT(DISTINCT student_id) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        )""")
    total_students = cursor.fetchone()[0]

    # Average predicted score
    cursor.execute("""SELECT AVG(predicted_score) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        )""")
    average_score = cursor.fetchone()[0]

    # Performance counts
    cursor.execute(
        """SELECT COUNT(*) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        ) AND performance = %s""",
        ("Excellent",)
    )
    excellent = cursor.fetchone()[0]

    cursor.execute(
        """SELECT COUNT(*) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        ) AND performance = %s""",
        ("Good",)
    )
    good = cursor.fetchone()[0]

    cursor.execute(
        """SELECT COUNT(*) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        ) AND performance = %s""",
        ("Average",)
    )
    average = cursor.fetchone()[0]

    cursor.execute(
        """SELECT COUNT(*) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        ) AND performance = %s""",
        ("Poor",)
    )
    poor = cursor.fetchone()[0]

    performance_data = {
        "Excellent": excellent,
        "Good": good,
        "Average": average,
        "Poor": poor
    }

    # Risk counts
    cursor.execute(
        """SELECT COUNT(*) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        ) AND risk_level = %s""",
        ("High Risk",)
    )
    high_risk = cursor.fetchone()[0]

    cursor.execute(
        """SELECT COUNT(*) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        ) AND risk_level = %s""",
        ("Low Risk",)
    )
    low_risk = cursor.fetchone()[0]

    cursor.execute(
        """SELECT COUNT(*) FROM predictions WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        ) AND risk_level = %s""",
        ("Medium Risk",)
    )
    medium_risk = cursor.fetchone()[0]

    risk_data = {
        "Low Risk": low_risk,
        "Medium Risk": medium_risk,
        "High Risk": high_risk
    }

    # -----------------------------
    # All Students Pagination
    # -----------------------------

    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    search = request.args.get("search", "").strip()

    students_per_page = 20

    # Latest prediction for every student
    base_query = """
        SELECT student_name,
               student_id,
               predicted_score,
               performance,
               risk_level
        FROM predictions
        WHERE NOT (
            student_name = student_id
            AND (
                student_id ~ '^S[0-9]{3}$'
                OR student_id = 'S1000'
            )
        )
        AND id IN (
            SELECT MAX(id)
            FROM predictions
            WHERE NOT (
                student_name = student_id
                AND (
                    student_id ~ '^S[0-9]{3}$'
                    OR student_id = 'S1000'
                )
            )
            GROUP BY student_id
        )
    """

    # Search by student name or student ID
    if search:
        base_query += """
            AND (
                student_name LIKE %s
                OR student_id LIKE %s
            )
        """

        search_value = f"%{search}%"

        cursor.execute(
            "SELECT COUNT(*) FROM (" + base_query + ")",
            (search_value, search_value)
        )

        filtered_total = cursor.fetchone()[0]

        total_pages = max(
            1,
            (filtered_total + students_per_page - 1) // students_per_page
        )

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * students_per_page

        base_query += """
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """

        cursor.execute(
            base_query,
            (search_value, search_value, students_per_page, offset)
        )

    else:
        cursor.execute(
            "SELECT COUNT(*) FROM (" + base_query + ")"
        )

        filtered_total = cursor.fetchone()[0]

        total_pages = max(
            1,
            (filtered_total + students_per_page - 1) // students_per_page
        )

        if page > total_pages:
            page = total_pages

        offset = (page - 1) * students_per_page

        base_query += """
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """

        cursor.execute(
            base_query,
            (students_per_page, offset)
        )

    students = cursor.fetchall()

    # High-risk students
    cursor.execute("""
        SELECT student_name,
               student_id,
               predicted_score,
               performance,
               risk_level
        FROM predictions
        WHERE risk_level = %s
          AND NOT (
              student_name = student_id
              AND (
                  student_id ~ '^S[0-9]{3}$'
                  OR student_id = 'S1000'
              )
          )
          AND id IN (
              SELECT MAX(id)
              FROM predictions
              GROUP BY student_id
          )
        ORDER BY predicted_score ASC
    """, ("High Risk",))

    high_risk_students = cursor.fetchall()

    conn.close()

    if average_score is None:
        average_score = 0

    return render_template(
        "teacher_dashboard.html",
        username=session.get("username"),
        total_students=total_students,
        average_score=round(average_score, 2),
        excellent=excellent,
        good=good,
        average=average,
        poor=poor,
        high_risk=high_risk,
        students=students,
        high_risk_students=high_risk_students,
        performance_data=performance_data,
        risk_data=risk_data,
        page=page,
        total_pages=total_pages,
        search=search
    )


@app.route("/bulk-upload", methods=["GET", "POST"])
def bulk_upload():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Only teachers can use Bulk CSV Upload."

    if request.method == "GET":
        return render_template("bulk_upload.html")

    file = request.files.get("file")

    if not file or file.filename == "":
        return "Please select a CSV file."

    if not file.filename.lower().endswith(".csv"):
        return "Please upload a CSV file."

    try:
        file_content = file.stream.read().decode("utf-8-sig").splitlines()
        reader = csv.DictReader(file_content)

        required_columns = [
            "Student_ID",
            "Study_Hours",
            "Attendance",
            "Previous_Score",
            "Assignments_Completed",
            "Sleep_Hours",
            "Participation"
        ]

        if not reader.fieldnames:
            return "CSV file is empty."

        missing_columns = [
            column
            for column in required_columns
            if column not in reader.fieldnames
        ]

        if missing_columns:
            return "Missing columns: " + ", ".join(missing_columns)

        conn = psycopg.connect(os.environ["DATABASE_URL"])
        cursor = conn.cursor()

        processed = 0

        for row in reader:

            student_id = row["Student_ID"].strip()
            student_name = (row.get("Student_Name") or "").strip()
            if not student_name:
                student_name = student_id

            study_hours = float(row["Study_Hours"])
            attendance = float(row["Attendance"])
            previous_score = float(row["Previous_Score"])
            assignments_completed = int(row["Assignments_Completed"])
            sleep_hours = float(row["Sleep_Hours"])
            participation = int(row["Participation"])

            if not 1 <= study_hours <= 8:
                continue

            if not 50 <= attendance <= 100:
                continue

            if not 40 <= previous_score <= 95:
                continue

            if not 0 <= assignments_completed <= 10:
                continue

            if not 4 <= sleep_hours <= 9:
                continue

            if not 0 <= participation <= 10:
                continue

            prediction = model.predict([[
                study_hours,
                attendance,
                previous_score,
                assignments_completed,
                sleep_hours,
                participation
            ]])

            predicted_score = round(prediction[0], 2)

            if predicted_score >= 85:
                performance = "Excellent"
                recommendation = "Keep up the excellent performance!"
                risk_level = "Low Risk"

            elif predicted_score >= 70:
                performance = "Good"
                recommendation = "Good performance. Focus on consistency to improve further."
                risk_level = "Medium Risk"

            elif predicted_score >= 50:
                performance = "Average"
                recommendation = "Increase study hours and assignment completion."
                risk_level = "High Risk"

            else:
                performance = "Poor"
                recommendation = "Improve attendance, study time and participation."
                risk_level = "High Risk"

            cursor.execute("""
                INSERT INTO predictions
                (
                    student_name,
                    student_id,
                    predicted_score,
                    performance,
                    recommendation,
                    user_id,
                    risk_level,
                    study_hours,
                    attendance,
                    previous_score,
                    assignments_completed,
                    sleep_hours,
                    participation,
                    prediction_date
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS'))
            """, (
                student_name,
                student_id,
                predicted_score,
                performance,
                recommendation,
                (session["user_id"] if session.get("role") == "student" else None),
                risk_level,
                study_hours,
                attendance,
                previous_score,
                assignments_completed,
                sleep_hours,
                participation
            ))

            processed += 1

        conn.commit()
        conn.close()

        return render_template(
            "bulk_upload.html",
            success=f"{processed} student records processed successfully."
        )

    except ValueError:
        return "Invalid numeric value found in CSV."

    except Exception as e:
        return f"Error processing CSV: {str(e)}"
    
@app.route("/student-history")
def student_history():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "student":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            student_name,
            student_id,
            predicted_score,
            performance,
            risk_level,
            recommendation
        FROM predictions
        WHERE user_id = %s
        ORDER BY id DESC
    """, (session["user_id"],))

    predictions = cursor.fetchall()

    conn.close()

    return render_template(
        "student_history.html",
        username=session.get("username"),
        predictions=predictions
    ) 
    
@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))

@app.route("/predict", methods=["POST"])
def predict():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") not in ["student", "teacher"]:
        return "Access denied."

    student_name = request.form.get("student_name", "").strip()
    student_id = request.form.get("student_id", "").strip()

    if not student_name:
        return "Student Name cannot be empty."

    if not student_id:
        return "Student ID cannot be empty."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    if session.get("role") == "student":
        cursor.execute(
            "SELECT student_name, student_id FROM users WHERE id = %s AND role = 'student'",
            (session["user_id"],)
        )
        registered_student = cursor.fetchone()

        if not registered_student or not registered_student[1]:
            conn.close()
            return "Your registered Student ID was not found. Please contact your teacher."

        registered_name, registered_id = registered_student

        if student_id.strip() != registered_id.strip():
            conn.close()
            return "Student ID mismatch. Please use your registered Student ID."

        student_id = registered_id.strip()
        student_name = (registered_name or student_name).strip()


    


    try:
        study_hours = float(request.form["study_hours"])
        attendance = float(request.form["attendance"])
        previous_score = float(request.form["previous_score"])
        total_assignments = int(request.form["total_assignments"])
        assignments_completed = int(request.form["assignments_completed"])
        sleep_hours = float(request.form["sleep_hours"])
        participation = int(request.form["participation"])
    except (ValueError, KeyError):
        conn.close()
        return "Please enter valid numeric values for all fields."

    if not 1 <= total_assignments <= 100:
        conn.close()
        return "Total Assignments must be between 1 and 100."

    if not 0 <= assignments_completed <= total_assignments:
        conn.close()
        return "Completed Assignments must be between 0 and Total Assignments."

    completion_rate = (assignments_completed / total_assignments) * 100
    assignment_model_score = (completion_rate / 100) * 10

    if not 1 <= study_hours <= 8:
        conn.close()
        return "Study Hours must be between 1 and 8."

    if not 50 <= attendance <= 100:
        conn.close()
        return "Attendance must be between 50 and 100."

    if not 40 <= previous_score <= 95:
        conn.close()
        return "Previous Score must be between 40 and 95."


    if not 4 <= sleep_hours <= 9:
        conn.close()
        return "Sleep Hours must be between 4 and 9."

    if not 0 <= participation <= 10:
        conn.close()
        return "Participation must be between 0 and 10."

    prediction = model.predict([[
        study_hours,
        attendance,
        previous_score,
        assignment_model_score,
        sleep_hours,
        participation
    ]])

    predicted_score = round(float(prediction[0]), 2)

    if predicted_score >= 85:
        performance = "Excellent"
    elif predicted_score >= 70:
        performance = "Good"
    elif predicted_score >= 50:
        performance = "Average"
    else:
        performance = "Poor"

    recommendations = []

    if attendance < 75:
        recommendations.append("Improve attendance to at least 75%.")

    if study_hours < 4:
        recommendations.append("Increase daily study hours.")

    if completion_rate < 70:
        recommendations.append("Complete more assignments regularly.")

    if participation < 5:
        recommendations.append("Increase classroom participation.")

    if sleep_hours < 6:
        recommendations.append("Maintain at least 6 hours of sleep.")

    if previous_score < 60:
        recommendations.append("Focus on strengthening your previous weak areas.")

    if recommendations:
        recommendation = " ".join(recommendations)
    else:
        recommendation = (
            "Great work! Your academic habits are well balanced. "
            "Keep maintaining your consistency."
        )

    if predicted_score >= 85:
        risk_level = "Low Risk"
    elif predicted_score >= 70:
        risk_level = "Medium Risk"
    else:
        risk_level = "High Risk"

    cursor.execute("""
        INSERT INTO predictions
        (
            student_name,
            student_id,
            predicted_score,
            performance,
            recommendation,
            user_id,
            risk_level,
            study_hours,
            attendance,
            previous_score,
            assignments_completed,
            sleep_hours,
            participation,
            prediction_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD HH24:MI:SS'))
    """, (
        student_name,
        student_id,
        predicted_score,
        performance,
        recommendation,
        (session["user_id"] if session.get("role") == "student" else None),
        risk_level,
        study_hours,
        attendance,
        previous_score,
        assignments_completed,
        sleep_hours,
        participation
    ))

    conn.commit()
    conn.close()

    return render_template(
        "result.html",
        student_name=student_name,
        student_id=student_id,
        predicted_score=predicted_score,
        performance=performance,
        recommendation=recommendation,
        study_hours=study_hours,
        attendance=attendance,
        previous_score=previous_score,
        assignments_completed=assignments_completed,
        sleep_hours=sleep_hours,
        participation=participation,
        role=session.get("role")
    )

@app.route("/history")
def history():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    if session.get("role") == "student":

        # Get logged-in student's registered Student ID
        cursor.execute("""
            SELECT student_id
            FROM users
            WHERE id = %s
        """, (session["user_id"],))

        user_data = cursor.fetchone()

        if not user_data:
            conn.close()
            return "Student account not found."

        registered_student_id = user_data[0]

        # Show only this student's history
        cursor.execute("""
            SELECT
                student_name,
                student_id,
                predicted_score,
                performance
            FROM predictions
            WHERE user_id = %s
              AND TRIM(student_id) = %s
            ORDER BY id DESC
        """, (session["user_id"], registered_student_id.strip()))

    elif session.get("role") == "teacher":

        # Teacher can see all students
        cursor.execute("""
            SELECT
                student_name,
                student_id,
                predicted_score,
                performance
            FROM predictions
            WHERE NOT (
                student_name = student_id
                AND (
                    student_id ~ '^S[0-9]{3}$'
                    OR student_id = 'S1000'
                )
            )
            ORDER BY id DESC
        """)

    else:

        conn.close()
        return "Access denied."

    predictions = cursor.fetchall()

    conn.close()

    return render_template(
        "history.html",
        predictions=predictions
    )
     
@app.route("/export")
def export_predictions():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Only teachers can export student reports."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            student_name,
            student_id,
            predicted_score,
            performance,
            risk_level,
            study_hours,
            attendance,
            previous_score,
            assignments_completed,
            sleep_hours,
            participation,
            recommendation
        FROM predictions
        ORDER BY id DESC
    """)

    predictions = cursor.fetchall()

    conn.close()

    def generate():

        yield (
            "Student Name,Student ID,Predicted Score,Performance,"
            "Risk Level,Study Hours,Attendance,Previous Score,"
            "Assignments Completed,Sleep Hours,Participation,Recommendation\n"
        )

        for prediction in predictions:

            yield (
                f'"{prediction[0]}","{prediction[1]}",'
                f'"{prediction[2]}","{prediction[3]}",'
                f'"{prediction[4]}","{prediction[5]}",'
                f'"{prediction[6]}","{prediction[7]}",'
                f'"{prediction[8]}","{prediction[9]}",'
                f'"{prediction[10]}","{prediction[11]}"\n'
            )

    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=student_performance_report.csv"
        }
    )
     
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Access denied."
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM predictions")
    total_predictions = cursor.fetchone()[0]

    cursor.execute("SELECT AVG(predicted_score) FROM predictions")
    average_score = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM predictions WHERE performance = %s",
        ("Excellent",)
    )
    excellent = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM predictions WHERE performance = %s",
        ("Good",)
    )
    good = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM predictions WHERE performance = %s",
        ("Average",)
    )
    average = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM predictions WHERE performance = %s",
        ("Poor",)
    )
    poor = cursor.fetchone()[0]

    conn.close()

    if average_score is None:
        average_score = 0

    return render_template(
    "dashboard.html",
    total_predictions=total_predictions,
    average_score=round(average_score, 2),
    excellent=excellent,
    good=good,
    average=average,
    poor=poor,
    model_metrics=model_metrics
)
    
    
@app.route("/model-comparison")
def model_comparison():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "teacher":
        return "Only teachers can view model comparison."

    return render_template(
        "model_comparison.html",
        model_metrics=model_metrics
    )

@app.route("/student-progress")
def student_progress():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "student":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    # Get logged-in student's registered Student ID
    cursor.execute("""
        SELECT student_id
        FROM users
        WHERE id = %s
    """, (session["user_id"],))

    user_data = cursor.fetchone()

    if not user_data:
        conn.close()
        return "Student account not found."

    registered_student_id = user_data[0]

    # Show only the logged-in student's own predictions
    cursor.execute("""
        SELECT predicted_score, performance
        FROM predictions
        WHERE student_id = %s
        ORDER BY id ASC
    """, (registered_student_id,))

    progress_data = cursor.fetchall()
    conn.close()

    scores = [row[0] for row in progress_data]
    performances = [row[1] for row in progress_data]

    return render_template(
        "student_progress.html",
        scores=scores,
        performances=performances
    )

@app.route("/my-analytics")
def my_analytics():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "student":
        return "Access denied."

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cursor = conn.cursor()

    # Get logged-in student's registered details
    cursor.execute("""
        SELECT student_name, student_id
        FROM users
        WHERE id = %s
    """, (session["user_id"],))

    user_data = cursor.fetchone()

    if not user_data:
        conn.close()
        return "Student account not found."

    student_name, student_id = user_data

    # Complete prediction history
    cursor.execute("""
        SELECT
            student_name,
            student_id,
            predicted_score,
            performance,
            risk_level,
            study_hours,
            attendance,
            previous_score,
            assignments_completed,
            sleep_hours,
            participation,
            prediction_date
        FROM predictions
        WHERE student_id = %s
        ORDER BY prediction_date DESC, id DESC
    """, (student_id,))

    predictions = cursor.fetchall()

    # Week-wise average
    cursor.execute("""
        SELECT
            to_char(prediction_date::timestamp, 'IYYY-"W"IW') AS period,
            ROUND(AVG(predicted_score)::numeric, 2) AS average_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        GROUP BY period
        ORDER BY period
    """, (student_id,))

    weekly_data = cursor.fetchall()

    # Month-wise average
    cursor.execute("""
        SELECT
            to_char(prediction_date::timestamp, 'YYYY-MM') AS period,
            ROUND(AVG(predicted_score)::numeric, 2) AS average_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        GROUP BY period
        ORDER BY period
    """, (student_id,))

    monthly_data = cursor.fetchall()

    # Year-wise average
    cursor.execute("""
        SELECT
            to_char(prediction_date::timestamp, 'YYYY') AS period,
            ROUND(AVG(predicted_score)::numeric, 2) AS average_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        GROUP BY period
        ORDER BY period
    """, (student_id,))

    yearly_data = cursor.fetchall()

    # Individual dated predictions for graph
    cursor.execute("""
        SELECT
            prediction_date,
            predicted_score
        FROM predictions
        WHERE student_id = %s
        AND prediction_date IS NOT NULL
        ORDER BY prediction_date
    """, (student_id,))

    prediction_points = cursor.fetchall()

    conn.close()

    return render_template(
        "student_analytics.html",
        student_name=student_name,
        student_id=student_id,
        predictions=predictions,
        weekly_data=weekly_data,
        monthly_data=monthly_data,
        yearly_data=yearly_data,
        prediction_points=prediction_points
    )

if __name__ == "__main__":
    app.run(debug=True)
