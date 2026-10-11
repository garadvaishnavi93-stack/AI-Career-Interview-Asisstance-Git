import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from google import genai
from pypdf import PdfReader
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-for-production")
app.config["UPLOAD_FOLDER"] = BASE_DIR / "uploads"
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB
app.config["UPLOAD_FOLDER"].mkdir(exist_ok=True)

API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def get_db():
    connection = sqlite3.connect(BASE_DIR / "interviews.db")
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                job_description TEXT,
                resume_text TEXT,
                questions TEXT NOT NULL,
                answers TEXT NOT NULL DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )


def clean_json(text, fallback):
    """Remove Markdown fences and parse JSON; use a fallback if AI output is invalid."""
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def ask_gemini(prompt, fallback):
    """Call Gemini safely. The app remains usable without a key or during API errors."""
    if not client:
        return fallback
    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        return clean_json(response.text, fallback)
    except Exception:
        return fallback


def fallback_questions(role):
    return [
        {"question": f"Tell me about yourself and why you want to become a {role}.", "topic": "Introduction"},
        {"question": f"Which skills are most useful for a {role}, and how have you practiced them?", "topic": "Skills"},
        {"question": "Describe a project challenge you faced and how you solved it.", "topic": "Problem solving"},
        {"question": "How do you learn a new tool or technology?", "topic": "Learning"},
        {"question": "Why should we select you for this role?", "topic": "Motivation"},
    ]


def make_questions(role, job_description, resume_text):
    fallback = fallback_questions(role)
    prompt = f"""You are a supportive interviewer. Create exactly 5 beginner-friendly interview questions for the role: {role}.
Job description: {job_description[:2500] or "Not provided"}
Resume text: {resume_text[:2500] or "Not provided"}
Use the description and resume only to customize questions. Do not invent experience.
Include one introduction, two skill/role questions, one project question, and one behavioral question.
Return only valid JSON: [{{"question":"...", "topic":"..."}}]."""
    result = ask_gemini(prompt, fallback)
    return result if isinstance(result, list) and len(result) == 5 else fallback


def evaluate_answer(question, answer):
    fallback = {
        "score": 5,
        "feedback": "Good attempt. Add one specific example and explain the result.",
        "improved_answer_tip": "Use Situation, Task, Action, Result (STAR) when giving examples.",
    }
    prompt = f"""Evaluate this interview answer for a beginner.
Question: {question}
Answer: {answer[:4000]}
Give constructive, honest feedback. Score from 1 to 10. Do not claim the answer is correct if it is vague or inaccurate.
Return only JSON: {{"score": number, "feedback":"2-3 sentences", "improved_answer_tip":"one practical tip"}}."""
    result = ask_gemini(prompt, fallback)
    if not isinstance(result, dict):
        return fallback
    try:
        score = max(1, min(10, int(result.get("score", 5))))
    except (TypeError, ValueError):
        score = 5
    return {
        "score": score,
        "feedback": str(result.get("feedback", fallback["feedback"])),
        "improved_answer_tip": str(result.get("improved_answer_tip", fallback["improved_answer_tip"])),
    }


def extract_pdf_text(uploaded_file):
    """Extract text from a text-based PDF, then delete the temporary upload."""
    safe_name = secure_filename(uploaded_file.filename) or "resume.pdf"
    path = app.config["UPLOAD_FOLDER"] / safe_name
    uploaded_file.save(path)
    try:
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text[:6000]
    finally:
        path.unlink(missing_ok=True)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "").strip()
        job_description = request.form.get("job_description", "").strip()
        resume_text = ""
        resume = request.files.get("resume")

        if not name or not role:
            flash("Please enter your name and target role.")
            return redirect(url_for("index"))
        if resume and resume.filename:
            if not resume.filename.lower().endswith(".pdf"):
                flash("Please upload a PDF resume.")
                return redirect(url_for("index"))
            try:
                resume_text = extract_pdf_text(resume)
            except Exception:
                flash("We could not read that PDF. Try a text-based PDF.")

        questions = make_questions(role, job_description, resume_text)
        with get_db() as connection:
            cursor = connection.execute(
                "INSERT INTO interviews (name, role, job_description, resume_text, questions) VALUES (?, ?, ?, ?, ?)",
                (name, role, job_description, resume_text, json.dumps(questions)),
            )
            interview_id = cursor.lastrowid
        session["interview_id"] = interview_id
        session["question_index"] = 0
        return redirect(url_for("interview"))
    return render_template("index.html")


@app.route("/interview", methods=["GET", "POST"])
def interview():
    interview_id = session.get("interview_id")
    if not interview_id:
        return redirect(url_for("index"))

    with get_db() as connection:
        row = connection.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,)).fetchone()
    if not row:
        return redirect(url_for("index"))

    questions = json.loads(row["questions"])
    answers = json.loads(row["answers"])
    question_index = session.get("question_index", 0)
    if question_index >= len(questions):
        return redirect(url_for("report"))

    if request.method == "POST":
        answer = request.form.get("answer", "").strip()
        if len(answer) < 15:
            flash("Please write at least a couple of sentences.")
            return redirect(url_for("interview"))
        current = questions[question_index]
        evaluation = evaluate_answer(current["question"], answer)
        answers.append({"question": current["question"], "topic": current["topic"], "answer": answer, **evaluation})
        with get_db() as connection:
            connection.execute("UPDATE interviews SET answers = ? WHERE id = ?", (json.dumps(answers), interview_id))
        session["question_index"] = question_index + 1
        return redirect(url_for("report") if question_index + 1 == len(questions) else url_for("interview"))

    return render_template(
        "interview.html",
        candidate=row["name"], role=row["role"], item=questions[question_index],
        number=question_index + 1, total=len(questions),
    )


@app.route("/report")
def report():
    interview_id = session.get("interview_id")
    if not interview_id:
        return redirect(url_for("index"))
    with get_db() as connection:
        row = connection.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,)).fetchone()
    if not row:
        return redirect(url_for("index"))
    answers = json.loads(row["answers"])
    average = round(sum(item["score"] for item in answers) / len(answers), 1) if answers else 0
    return render_template("report.html", candidate=row["name"], role=row["role"], answers=answers, average=average)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
