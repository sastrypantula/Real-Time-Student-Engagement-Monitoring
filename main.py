"""
Classroom Attention Monitoring - FastAPI Backend
Run with: uvicorn main:app --reload --port 8000
"""

import cv2
import mediapipe as mp
import numpy as np
import time
import threading
import asyncio
from collections import deque
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI App Setup
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Classroom Attention Monitor API")

# Allow frontend (React) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # In production, replace * with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# MediaPipe Setup
# ─────────────────────────────────────────────────────────────────────────────
import os
model_path = os.path.join(os.path.dirname(__file__), "classroom-dashboard/model1/face_landmarker.task")
base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_faces=1,
)
detector = vision.FaceLandmarker.create_from_options(options)

# ─────────────────────────────────────────────────────────────────────────────
# Eye Landmark Indices & Thresholds
# ─────────────────────────────────────────────────────────────────────────────
LEFT_EYE  = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

EAR_THRESHOLD        = 0.23
EYE_CONTACT_THRESHOLD = 60   # % for "not active" alert
SLEEP_SECONDS        = 5     # seconds of closed eyes → sleepy alert

# ─────────────────────────────────────────────────────────────────────────────
# Shared State  (written by CV thread, read by API endpoints)
# ─────────────────────────────────────────────────────────────────────────────
state = {
    # Session control
    "running": False,

    # Live metrics (updated every frame)
    "ear":            1.0,      # Eye Aspect Ratio
    "is_sleepy":      False,
    "eye_contact_pct": 100.0,   # % in last 5-sec window
    "face_detected":  False,

    # Computed scores (0-100)
    "attention_score": 0,
    "attentive_pct":   0,
    "confused_pct":    0,
    "distracted_pct":  0,

    # System
    "fps":        0.0,
    "cpu_usage":  0.0,
    "memory_mb":  0.0,

    # Heatmap — 5×5 grid, single student repeated for demo
    # In multi-student mode you'd have one entry per student
    "heatmap": [["attentive"] * 5 for _ in range(5)],

    # Timeline ring buffer (last 60 data points)
    "timeline": deque(maxlen=60),

    # Per-topic engagement (dummy unless you track topics separately)
    "topic_engagement": [
        {"topic": "Math",        "engagement": 70},
        {"topic": "Physics",     "engagement": 55},
        {"topic": "Programming", "engagement": 80},
    ],

    # Session history (accumulated across current session)
    "session_data": [],

    # Optimization extras
    "inference_time_ms": 0.0,
    "model_size_mb":     8.0,
    "quantization_pct":  87.0,
}

state_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# EAR helper
# ─────────────────────────────────────────────────────────────────────────────
def calculate_EAR(eye: np.ndarray) -> float:
    v1 = np.linalg.norm(eye[1] - eye[5])
    v2 = np.linalg.norm(eye[2] - eye[4])
    h  = np.linalg.norm(eye[0] - eye[3])
    if h == 0:
        return 1.0
    return (v1 + v2) / (2.0 * h)

# ─────────────────────────────────────────────────────────────────────────────
# Compute attention / confusion / distraction scores from raw signals
#
#   attentive  → eyes open  AND making eye contact
#   confused   → eyes open  AND NOT making eye contact (looking away)
#   distracted → eyes closed (or sleepy)
# ─────────────────────────────────────────────────────────────────────────────
def compute_scores(ear: float, eye_contact_pct: float, face_detected: bool):
    if not face_detected:
        # No face → treat as distracted
        return 0, 0, 0, 100

    eyes_open = ear >= EAR_THRESHOLD
    engaged   = eye_contact_pct >= EYE_CONTACT_THRESHOLD

    if eyes_open and engaged:
        attentive, confused, distracted = 80, 10, 10
    elif eyes_open and not engaged:
        attentive, confused, distracted = 20, 60, 20
    else:   # eyes closed
        attentive, confused, distracted = 5, 10, 85

    # Attention score = weighted blend
    attention = int(attentive * 0.7 + (eye_contact_pct * 0.3))
    attention = max(0, min(100, attention))

    return attention, attentive, confused, distracted

# ─────────────────────────────────────────────────────────────────────────────
# Map current state to heatmap cell label
# ─────────────────────────────────────────────────────────────────────────────
def state_to_label(attentive_pct: int, confused_pct: int) -> str:
    if attentive_pct >= 60:
        return "attentive"
    elif confused_pct >= 40:
        return "confused"
    return "distracted"

# ─────────────────────────────────────────────────────────────────────────────
# CV Worker Thread
# ─────────────────────────────────────────────────────────────────────────────
def cv_worker():
    cap = cv2.VideoCapture(0)
    cam_fps = cap.get(cv2.CAP_PROP_FPS) or 30

    CLOSED_THRESHOLD  = int(SLEEP_SECONDS * cam_fps)
    WINDOW_THRESHOLD  = int(5 * cam_fps)   # 5-sec engagement window

    closed_frames      = 0
    sleep_triggered    = False
    window_frames      = 0
    eye_contact_frames = 0

    frame_times = deque(maxlen=30)

    print("[CV] Worker started.")

    while True:
        with state_lock:
            if not state["running"]:
                break

        t0 = time.perf_counter()
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.03)
            continue

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts = int(time.time() * 1000)

        inf_start = time.perf_counter()
        result = detector.detect_for_video(mp_img, ts)
        inf_ms = (time.perf_counter() - inf_start) * 1000

        face_detected = bool(result.face_landmarks)
        ear_val       = 1.0
        eye_contact_pct_local = 0.0

        if face_detected:
            landmarks = result.face_landmarks[0]
            h, w, _ = frame.shape
            coords = np.array([(int(p.x * w), int(p.y * h)) for p in landmarks])

            left_eye  = coords[LEFT_EYE]
            right_eye = coords[RIGHT_EYE]

            left_ear  = calculate_EAR(left_eye)
            right_ear = calculate_EAR(right_eye)
            ear_val   = (left_ear + right_ear) / 2.0

            # Sleep detection
            if ear_val < EAR_THRESHOLD:
                closed_frames += 1
            else:
                closed_frames  = 0
                sleep_triggered = False

            is_sleepy = False
            if closed_frames >= CLOSED_THRESHOLD and not sleep_triggered:
                is_sleepy      = True
                sleep_triggered = True
                print("⚠ ALERT: Student is SLEEPY")

            # Eye contact
            nose_x      = coords[1][0]
            left_face   = coords[234][0]
            right_face  = coords[454][0]
            face_center = (left_face + right_face) / 2.0

            window_frames += 1
            if abs(nose_x - face_center) < 30 and ear_val > EAR_THRESHOLD:
                eye_contact_frames += 1

            if window_frames >= WINDOW_THRESHOLD:
                eye_contact_pct_local = (eye_contact_frames / window_frames) * 100
                if eye_contact_pct_local < EYE_CONTACT_THRESHOLD:
                    print(f"⚠ ALERT: Student is NOT ACTIVE ({eye_contact_pct_local:.1f}%)")
                window_frames      = 0
                eye_contact_frames = 0
            else:
                # Running percentage within current window
                if window_frames > 0:
                    eye_contact_pct_local = (eye_contact_frames / window_frames) * 100

        # FPS
        frame_times.append(time.perf_counter())
        if len(frame_times) >= 2:
            elapsed = frame_times[-1] - frame_times[0]
            measured_fps = len(frame_times) / elapsed if elapsed > 0 else 0
        else:
            measured_fps = 0

        # Scores
        attention, attentive, confused, distracted = compute_scores(
            ear_val, eye_contact_pct_local, face_detected
        )

        cell_label = state_to_label(attentive, confused)
        new_heatmap = [[cell_label] * 5 for _ in range(5)]

        now_str = datetime.now().strftime("%H:%M:%S")

        with state_lock:
            state["ear"]              = round(ear_val, 3)
            state["is_sleepy"]        = closed_frames >= CLOSED_THRESHOLD
            state["eye_contact_pct"]  = round(eye_contact_pct_local, 1)
            state["face_detected"]    = face_detected
            state["attention_score"]  = attention
            state["attentive_pct"]    = attentive
            state["confused_pct"]     = confused
            state["distracted_pct"]   = distracted
            state["fps"]              = round(measured_fps, 1)
            state["inference_time_ms"] = round(inf_ms, 1)
            state["heatmap"]          = new_heatmap
            state["timeline"].append({"t": now_str, "score": attention})

    cap.release()
    print("[CV] Worker stopped.")

cv_thread: Optional[threading.Thread] = None

# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

# ── Session Control ───────────────────────────────────────────────────────────
@app.post("/api/session/start")
def session_start():
    global cv_thread
    with state_lock:
        if state["running"]:
            return {"ok": True, "message": "Already running"}
        state["running"]      = True
        state["timeline"]     = deque(maxlen=60)
        state["session_data"] = []

    cv_thread = threading.Thread(target=cv_worker, daemon=True)
    cv_thread.start()
    return {"ok": True, "message": "Session started"}


@app.post("/api/session/stop")
def session_stop():
    with state_lock:
        state["running"] = False
    if cv_thread:
        cv_thread.join(timeout=3)
    return {"ok": True, "message": "Session stopped"}


# ── Live Metrics  →  attention, attentive, confused, distracted ──────────────
@app.get("/api/live-metrics")
def live_metrics():
    with state_lock:
        return {
            "attention":  state["attention_score"],   # 0-100 overall score
            "attentive":  state["attentive_pct"],      # % of class attentive
            "confused":   state["confused_pct"],       # % confused
            "distracted": state["distracted_pct"],     # % distracted
            "ear":        state["ear"],                # raw EAR value
            "is_sleepy":  state["is_sleepy"],
            "face_detected": state["face_detected"],
        }


# ── Attention Timeline  →  last N data points ─────────────────────────────────
@app.get("/api/timeline")
def timeline():
    with state_lock:
        data = list(state["timeline"])
    # Return last 20 points to match frontend expectation
    return {"data": data[-20:]}


# ── Engagement by Topic ───────────────────────────────────────────────────────
@app.get("/api/engagement-by-topic")
def engagement_by_topic():
    """
    If you track which topic is being taught, update state['topic_engagement']
    from your lesson-management system. Right now it returns the stored values
    (seeded with dummy data on startup, real data as you update them).
    """
    with state_lock:
        # Blend current attention into current topic for a live feel
        topics = state["topic_engagement"].copy()
        att    = state["attention_score"]
        if topics:
            topics[0]["engagement"] = max(0, min(100, att))
    return {"data": topics}


# ── System Metrics ────────────────────────────────────────────────────────────
@app.get("/api/system-metrics")
def system_metrics():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.Process().memory_info().rss / (1024 * 1024)  # MB
    except ImportError:
        # psutil not installed → dummy values
        cpu = 35.0
        mem = 120.0

    with state_lock:
        fps = state["fps"]
        model_size = state["model_size_mb"]

    return {
        "cpu":       round(cpu, 1),
        "fps":       fps,
        "memory":    round(mem, 1),
        "modelSize": model_size,
    }


# ── Classroom Heatmap  →  5×5 grid ───────────────────────────────────────────
@app.get("/api/classroom-heatmap")
def classroom_heatmap():
    """
    Returns a 5×5 grid where each cell is one of:
      "attentive" | "confused" | "distracted"
    Currently all cells mirror the single detected student.
    For multi-student support, update state['heatmap'] per student in cv_worker.
    """
    with state_lock:
        grid = [row.copy() for row in state["heatmap"]]
    return {"grid": grid}


# ── Session Report  →  per-topic confusion + engagement ──────────────────────
@app.get("/api/session-report")
def session_report():
    """
    Returns accumulated per-topic stats for the session.
    Falls back to dummy data if session hasn't produced real data yet.
    """
    with state_lock:
        session = state["session_data"]

    if not session:
        # Dummy fallback so the frontend always has something to show
        session = [
            {"topic": "Math",        "confusion": 65, "engagement": 55},
            {"topic": "Physics",     "confusion": 20, "engagement": 75},
            {"topic": "Programming", "confusion": 15, "engagement": 88},
            {"topic": "History",     "confusion": 42, "engagement": 62},
            {"topic": "Chemistry",   "confusion": 58, "engagement": 48},
        ]

    return {"data": session}


# ── Optimization Metrics ──────────────────────────────────────────────────────
@app.get("/api/optimization-metrics")
def optimization_metrics():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        cpu = 35.0
        mem = 120.0

    with state_lock:
        fps      = state["fps"]
        inf_time = state["inference_time_ms"]
        model_sz = state["model_size_mb"]
        quant    = state["quantization_pct"]

    return {
        "cpu":           round(cpu, 1),
        "fps":           fps,
        "memory":        round(mem, 1),
        "inferenceTime": round(inf_time, 1),
        "modelSize":     model_sz,
        "quantization":  quant,
    }


# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    with state_lock:
        running = state["running"]
    return {"status": "ok", "session_running": running}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point (for direct python main.py run)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)