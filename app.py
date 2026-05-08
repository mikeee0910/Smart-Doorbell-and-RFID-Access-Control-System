from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    ImageMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

from line_config import (
    CHANNEL_ACCESS_TOKEN,
    CHANNEL_SECRET,
    NGROK_URL
)

import cv2
import os
import time
import threading
import queue
import sqlite3

try:
    import serial
except ImportError:
    serial = None


app = Flask(__name__)

# =========================
# Basic Settings
# =========================

IMAGE_PATH = "static/latest.jpg"
CAMERA_ID = 0
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "door_logs.db")

STM32_PORT = "/dev/ttyACM0"
BAUDRATE = 115200

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


# =========================
# System State
# =========================

door_locked = True

MAX_HISTORY = 10

# 不放在 config，第一次收到 LINE 訊息時自動設定
admin_user_id = None

# STM32 指令佇列：Flask 不直接讀 UART，避免跟背景監聽搶資料
stm32_command_queue = queue.Queue()

# STM32 連線狀態
stm32_connected = False


# =========================
# History Functions
# =========================

def init_db():
    """
    建立 SQLite log 資料表。
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                source TEXT NOT NULL,
                detail TEXT
            )
        """)
        conn.commit()


def add_history(action, source="LINE", detail=None):
    """
    action: 顯示在 LINE 歷史紀錄上的簡短動作
    source: 來源，例如 LINE 指令 / STM32 / 自動推播
    detail: debug 用細節，不顯示在 LINE 歷史紀錄
    """
    init_db()

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO history_logs (created_at, action, source, detail)
            VALUES (?, ?, ?, ?)
            """,
            (timestamp, action, source, detail)
        )

        conn.execute(
            """
            DELETE FROM history_logs
            WHERE id NOT IN (
                SELECT id
                FROM history_logs
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (MAX_HISTORY,)
        )

        conn.commit()


def get_history_text():
    """
    LINE 上簡短顯示：
    時間在上
    指令 / 動作在下
    不顯示 detail，不顯示 STM32 錯誤原因
    """
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT created_at, action
            FROM history_logs
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

    if not rows:
        return "目前尚無紀錄"

    text = "最近紀錄：\n"

    for i, row in enumerate(rows, start=1):
        text += f"{i}. {row['created_at']}\n"
        text += f"   {row['action']}\n\n"

    return text.strip()


# =========================
# Camera Functions
# =========================

def capture_photo_once():
    """
    拍照時才開啟 USB Webcam，拍完立即關閉。
    """
    cap = cv2.VideoCapture(CAMERA_ID)

    if not cap.isOpened():
        print("Cannot open USB webcam")
        return False

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    frame = None
    ret = False

    # 丟掉前幾張，避免曝光不穩或舊畫面
    for _ in range(5):
        ret, frame = cap.read()
        time.sleep(0.05)

    cap.release()

    if not ret or frame is None:
        print("Failed to capture image")
        return False

    os.makedirs("static", exist_ok=True)
    cv2.imwrite(IMAGE_PATH, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])

    print("Photo saved:", IMAGE_PATH)
    return True


def get_image_url():
    """
    LINE ImageMessage 需要 HTTPS URL。
    timestamp 用來避免圖片快取。
    """
    timestamp = int(time.time())
    image_url = f"{NGROK_URL}/static/latest.jpg?t={timestamp}"
    print("Image URL:", image_url)
    return image_url


# =========================
# LINE Push Function
# =========================

def push_doorbell_photo():
    """
    STM32 傳 DOORBELL 時，主動推播照片給管理員。
    """
    global admin_user_id

    if admin_user_id is None:
        print("No admin_user_id yet. Send any message to the bot first.")
        add_history("門鈴觸發但尚未設定管理員", "STM32")
        return

    add_history("門鈴觸發", "STM32")

    ok = capture_photo_once()

    if ok:
        add_history("門鈴拍照成功", "自動推播")
        image_url = get_image_url()

        messages = [
            TextMessage(text="有人按門鈴，照片如下："),
            ImageMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            )
        ]
    else:
        add_history("門鈴拍照失敗", "自動推播")
        print("Doorbell photo capture failed")

        messages = [
            TextMessage(text="有人按門鈴，但拍照失敗")
        ]

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=admin_user_id,
                    messages=messages
                )
            )

        print("Doorbell push message sent")

    except Exception as e:
        print("LINE push error:", e)


# =========================
# STM32 Serial Worker
# =========================

def stm32_worker():
    """
    只讓這個 thread 負責讀寫 STM32 UART。
    避免 LINE 指令和背景監聽同時讀 UART，造成 OK_UNLOCKED 被讀走。
    """
    global stm32_connected

    if serial is None:
        print("pyserial is not installed. Run: pip install pyserial")
        return

    try:
        ser = serial.Serial(STM32_PORT, BAUDRATE, timeout=0.2)
        time.sleep(2)
        stm32_connected = True
        print("STM32 serial connected:", STM32_PORT)

    except Exception as e:
        stm32_connected = False
        print("STM32 serial connection failed:", e)
        print("If STM32 is not connected yet, you can ignore this message.")
        return

    while True:
        try:
            # 優先處理 LINE 指令，例如 UNLOCK / LOCK / STATUS
            try:
                command, response_queue = stm32_command_queue.get_nowait()

                print("Send to STM32:", command)

                ser.reset_input_buffer()
                ser.write((command + "\n").encode())
                ser.flush()

                response = ""

                start_time = time.time()
                timeout_sec = 2.0

                while time.time() - start_time < timeout_sec:
                    line = ser.readline().decode(errors="ignore").strip()

                    if line:
                        print("STM32 response:", line)
                        response = line
                        break

                if response == "":
                    response = "NO_RESPONSE"

                response_queue.put(response)

            except queue.Empty:
                # 沒有 LINE 指令時，才讀 STM32 主動事件，例如 DOORBELL
                line = ser.readline().decode(errors="ignore").strip()

                if line:
                    print("STM32:", line)

                if line == "DOORBELL":
                    print("Doorbell pressed")
                    threading.Thread(target=push_doorbell_photo, daemon=True).start()

        except Exception as e:
            stm32_connected = False
            print("STM32 worker error:", e)
            time.sleep(1)


def send_command_to_stm32(command, timeout_sec=3.0):
    """
    Flask handler 呼叫這個函式送指令給 STM32。
    實際 UART 讀寫由 stm32_worker 處理。
    """
    if serial is None:
        return "PYSERIAL_NOT_INSTALLED"

    if not stm32_connected:
        return "STM32_NOT_CONNECTED"

    response_queue = queue.Queue()
    stm32_command_queue.put((command, response_queue))

    try:
        result = response_queue.get(timeout=timeout_sec)
        return result

    except queue.Empty:
        return "NO_RESPONSE"


# =========================
# Flask Routes
# =========================

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)

    except InvalidSignatureError:
        print("Invalid signature. Check Channel secret.")
        abort(400)

    except Exception as e:
        print("Webhook error:", e)
        abort(500)

    return "OK", 200


@app.route("/test_doorbell", methods=["GET"])
def test_doorbell():
    """
    不接 STM32 時，可以用這個網址測試門鈴拍照推播：
    https://你的-ngrok網址.ngrok-free.app/test_doorbell
    """
    threading.Thread(target=push_doorbell_photo, daemon=True).start()
    return "Doorbell test started", 200


# =========================
# LINE Message Handler
# =========================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    global door_locked
    global admin_user_id

    user_text = event.message.text.strip()

    # 第一次收到 LINE 訊息時，自動記住管理員 user_id
    if admin_user_id is None:
        admin_user_id = event.source.user_id
        print("Admin user ID registered:", admin_user_id)

    print("User ID:", event.source.user_id)
    print("User text:", user_text)

    # -------------------------
    # 開門
    # -------------------------
    if user_text == "開門":
        result = send_command_to_stm32("UNLOCK")

        if result == "OK_UNLOCKED":
            door_locked = False
            add_history("開門成功", "LINE 指令")

            messages = [
                TextMessage(text="已開鎖")
            ]
        else:
            add_history("開門失敗", "LINE 指令", detail=result)
            print("Open door failed, STM32 response:", result)

            messages = [
                TextMessage(text="開鎖失敗，請確認門鎖狀態")
            ]

    # -------------------------
    # 關門
    # -------------------------
    elif user_text == "關門":
        result = send_command_to_stm32("LOCK")

        if result == "OK_LOCKED":
            door_locked = True
            add_history("關門成功", "LINE 指令")

            messages = [
                TextMessage(text="已鎖定")
            ]
        else:
            add_history("關門失敗", "LINE 指令", detail=result)
            print("Lock door failed, STM32 response:", result)

            messages = [
                TextMessage(text="鎖定失敗，請確認門鎖狀態")
            ]

    # -------------------------
    # 狀態
    # -------------------------
    elif user_text == "狀態":
        result = send_command_to_stm32("STATUS")

        if result == "LOCKED":
            door_locked = True
            add_history("狀態查詢：已鎖定", "LINE 指令")

            messages = [
                TextMessage(text="目前狀態：已鎖定")
            ]

        elif result == "UNLOCKED":
            door_locked = False
            add_history("狀態查詢：已開鎖", "LINE 指令")

            messages = [
                TextMessage(text="目前狀態：已開鎖")
            ]

        else:
            print("Status check failed, STM32 response:", result)
            add_history("狀態查詢失敗", "LINE 指令", detail=result)

            # LINE 上顯示簡化狀態，不顯示 debug 細節
            if door_locked:
                status_text = "目前狀態：已鎖定"
            else:
                status_text = "目前狀態：已開鎖"

            messages = [
                TextMessage(text=status_text)
            ]

    # -------------------------
    # 歷史紀錄
    # -------------------------
    elif user_text == "歷史紀錄" or user_text == "歷史狀態":
        messages = [
            TextMessage(text=get_history_text())
        ]

    # -------------------------
    # 拍照
    # -------------------------
    elif user_text == "拍照":
        ok = capture_photo_once()

        if ok:
            add_history("拍照成功", "LINE 指令")
            image_url = get_image_url()

            messages = [
                TextMessage(text="已拍照，照片如下："),
                ImageMessage(
                    original_content_url=image_url,
                    preview_image_url=image_url
                )
            ]
        else:
            add_history("拍照失敗", "LINE 指令")
            print("Capture photo failed")

            messages = [
                TextMessage(text="拍照失敗，請確認攝影機")
            ]

    # -------------------------
    # 其他訊息
    # -------------------------
    else:
        messages = [
            TextMessage(text="請使用下方選單：開門、關門、拍照、歷史紀錄")
        ]

    # 避免 LINE Developers Verify 的 dummy reply token 造成錯誤
    if event.reply_token.startswith("00000000000000000000000000000000"):
        return

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=messages
                )
            )

    except Exception as e:
        print("LINE reply error:", e)


# =========================
# Main
# =========================

if __name__ == "__main__":
    init_db()

    stm32_thread = threading.Thread(target=stm32_worker, daemon=True)
    stm32_thread.start()

    app.run(host="0.0.0.0", port=5000)
