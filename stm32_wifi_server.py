from flask import Flask, jsonify, request

import os
import sqlite3
import sys
import time


app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "door_logs.db")


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_uid(uid):
    if uid is None:
        return ""

    return str(uid).strip().replace(" ", "").replace(":", "").upper()


def init_db():
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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS authorized_uids (
                uid TEXT PRIMARY KEY,
                name TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS stm32_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                uid TEXT,
                allowed INTEGER,
                detail TEXT
            )
        """)

        conn.commit()


def add_history(action, source="STM32 WiFi", detail=None):
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO history_logs (created_at, action, source, detail)
            VALUES (?, ?, ?, ?)
            """,
            (now_text(), action, source, detail)
        )
        conn.commit()


def add_event(event_type, uid=None, allowed=None, detail=None):
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO stm32_events (created_at, event_type, uid, allowed, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now_text(), event_type, uid, allowed, detail)
        )
        conn.commit()


def get_authorized_uid(uid):
    init_db()

    normalized_uid = normalize_uid(uid)

    if normalized_uid == "":
        return None

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT uid, name
            FROM authorized_uids
            WHERE uid = ? AND enabled = 1
            """,
            (normalized_uid,)
        ).fetchone()

    return row


def read_payload():
    data = request.get_json(silent=True) or {}

    if not data:
        data = request.form.to_dict()

    if not data:
        data = request.args.to_dict()

    return data


def respond(payload, status=200):
    if request.args.get("plain") == "1":
        return payload.get("command", "OK"), status, {
            "Content-Type": "text/plain; charset=utf-8"
        }

    return jsonify(payload), status


@app.route("/stm32/doorbell", methods=["GET", "POST"])
def stm32_doorbell():
    add_event("DOORBELL")
    add_history("門鈴觸發", "STM32 WiFi")

    return respond({
        "ok": True,
        "event": "DOORBELL",
        "command": "OK"
    })


@app.route("/stm32/rfid", methods=["GET", "POST"])
def stm32_rfid():
    data = read_payload()
    uid = normalize_uid(data.get("uid"))

    if uid == "":
        add_event("RFID", detail="missing uid")

        return respond({
            "ok": False,
            "error": "missing uid",
            "command": "DENY"
        }, 400)

    authorized_uid = get_authorized_uid(uid)
    allowed = authorized_uid is not None
    add_event("RFID", uid=uid, allowed=int(allowed))

    if allowed:
        name = authorized_uid["name"] or uid
        add_history(f"{name} RFID 開門成功", "STM32 WiFi", detail=uid)

        return respond({
            "ok": True,
            "uid": uid,
            "name": authorized_uid["name"],
            "authorized": True,
            "command": "UNLOCK"
        })

    add_history("RFID 驗證失敗", "STM32 WiFi", detail=uid)

    return respond({
        "ok": True,
        "uid": uid,
        "authorized": False,
        "command": "DENY"
    })


@app.route("/stm32/event", methods=["GET", "POST"])
def stm32_event():
    data = read_payload()
    event_type = str(data.get("event", "")).strip().upper()

    if event_type == "DOORBELL":
        return stm32_doorbell()

    if event_type == "RFID":
        return stm32_rfid()

    return respond({
        "ok": False,
        "error": "unknown event",
        "command": "DENY"
    }, 400)


def add_uid(uid, name=None):
    init_db()

    normalized_uid = normalize_uid(uid)

    if normalized_uid == "":
        print("UID 不可為空")
        return 1

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO authorized_uids (uid, name, enabled, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(uid) DO UPDATE SET
                name = excluded.name,
                enabled = 1
            """,
            (normalized_uid, name, now_text())
        )
        conn.commit()

    print(f"已新增/啟用 UID: {normalized_uid}")
    return 0


def list_uids():
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT uid, name, enabled, created_at
            FROM authorized_uids
            ORDER BY created_at DESC
            """
        ).fetchall()

    if not rows:
        print("目前沒有合法 UID")
        return 0

    for uid, name, enabled, created_at in rows:
        status = "啟用" if enabled else "停用"
        display_name = name or "-"
        print(f"{uid} | {display_name} | {status} | {created_at}")

    return 0


def disable_uid(uid):
    init_db()

    normalized_uid = normalize_uid(uid)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE authorized_uids SET enabled = 0 WHERE uid = ?",
            (normalized_uid,)
        )
        conn.commit()

    print(f"已停用 UID: {normalized_uid}")
    return 0


def print_usage():
    print("用法：")
    print("  python3 stm32_wifi_server.py")
    print("  python3 stm32_wifi_server.py add-uid <UID> [名稱]")
    print("  python3 stm32_wifi_server.py list-uids")
    print("  python3 stm32_wifi_server.py disable-uid <UID>")


if __name__ == "__main__":
    init_db()

    if len(sys.argv) >= 2:
        command = sys.argv[1]

        if command == "add-uid" and len(sys.argv) >= 3:
            name = sys.argv[3] if len(sys.argv) >= 4 else None
            raise SystemExit(add_uid(sys.argv[2], name))

        if command == "list-uids":
            raise SystemExit(list_uids())

        if command == "disable-uid" and len(sys.argv) >= 3:
            raise SystemExit(disable_uid(sys.argv[2]))

        print_usage()
        raise SystemExit(1)

    app.run(host="0.0.0.0", port=5001)
