import json
import os
import re
import sqlite3
from datetime import datetime
from html import unescape

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://edchemy.azaleakids.in/api/v2/external/call"

STUDENT_GUID = os.environ["EDCHEMY_STUDENT_GUID"]
USER_ID = os.environ["EDCHEMY_USER_ID"]
ACADEMIC_YEAR_ID = os.environ["EDCHEMY_ACADEMIC_YEAR_ID"]

AUTHORIZATION = os.environ["EDCHEMY_AUTH"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Your Telegram chat ID
TELEGRAM_CHAT_ID = "7425815660"

DB_FILE = "monitor_state.db"


# ============================================================
# EDCHEMY API
# ============================================================

def edchemy_api(payload):

    headers = {
        "authorization": AUTHORIZATION,
        "accept": (
            "application/json, text/javascript, "
            "*/*; q=0.01"
        ),
        "content-type": "application/json",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/153.0.0.0 Safari/537.36"
        ),
    }

    response = requests.post(
        API_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )

    print("Edchemy HTTP status:", response.status_code)

    if response.status_code != 200:
        raise RuntimeError(
            f"Edchemy API failed: HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response


def get_diary_list():

    payload = {
        "student_guids": f"'{STUDENT_GUID}'",
        "call_meta_data":
            "all.interaction.DiaryService.getDiarysForStudent",
        "user_id": USER_ID,
        "academic_year_id": ACADEMIC_YEAR_ID,
    }

    response = edchemy_api(payload)

    outer = response.json()

    data = outer.get("data")

    if isinstance(data, str):
        data = json.loads(data)

    if not isinstance(data, dict):
        raise RuntimeError(
            "Unexpected Edchemy diary-list response."
        )

    return data.get("live", [])


# ============================================================
# REPORT FORMATTING
# ============================================================

def html_to_text(html):

    if not html:
        return ""

    text = unescape(html)

    text = re.sub(
        r"<br\s*/?>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"</p\s*>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def format_report(report):

    publish_date = report.get("publish_date", "")
    description = html_to_text(
        report.get("description", "")
    )

    try:
        date_obj = datetime.strptime(
            publish_date,
            "%Y-%m-%d",
        )

        formatted_date = date_obj.strftime(
            "%a, %-d %b %Y"
        )

    except ValueError:
        formatted_date = publish_date

    message = (
        "📚 *Daily Class Report*\n"
        f"📅 {formatted_date}\n\n"
        f"{description}\n\n"
        "— Edchemy"
    )

    return message


# ============================================================
# LOCAL GITHUB STATE
# ============================================================

def initialize_db():

    connection = sqlite3.connect(DB_FILE)

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_reports (
            diary_id TEXT PRIMARY KEY,
            publish_date TEXT,
            sent_at TEXT
        )
        """
    )

    connection.commit()

    return connection


def already_sent(connection, diary_id):

    cursor = connection.execute(
        """
        SELECT 1
        FROM sent_reports
        WHERE diary_id = ?
        """,
        (diary_id,),
    )

    return cursor.fetchone() is not None


def mark_sent(connection, diary_id, publish_date):

    connection.execute(
        """
        INSERT OR IGNORE INTO sent_reports
        (
            diary_id,
            publish_date,
            sent_at
        )
        VALUES (?, ?, ?)
        """,
        (
            diary_id,
            publish_date,
            datetime.utcnow().isoformat(),
        ),
    )

    connection.commit()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        },
        timeout=30,
    )

    print(
        "Telegram HTTP status:",
        response.status_code,
    )

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram send failed: {data}"
        )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("EDCHEMY DAILY CLASS REPORT - GITHUB MONITOR")
    print("=" * 60)

    today = datetime.now().strftime("%Y-%m-%d")

    print("Today's date:", today)
    print("Checking Edchemy...")

    reports = get_diary_list()

    print(
        "Reports returned by Edchemy:",
        len(reports),
    )

    today_reports = [
        report
        for report in reports
        if report.get("publish_date") == today
        and report.get("title", "").strip()
        == "Daily Class Report"
    ]

    print(
        "Today's Daily Class Reports:",
        len(today_reports),
    )

    if not today_reports:

        print(
            "Today's Daily Class Report "
            "has not been published yet."
        )

        return

    connection = initialize_db()

    for report in today_reports:

        diary_id = report.get("diary_id")

        print()
        print("Diary ID:", diary_id)

        if already_sent(connection, diary_id):

            print(
                "Today's report has already "
                "been sent to Telegram."
            )

            continue

        message = format_report(report)

        print()
        print("Sending report to Telegram...")

        send_telegram(message)

        mark_sent(
            connection,
            diary_id,
            report.get("publish_date"),
        )

        print(
            "Report sent successfully and "
            "marked as sent."
        )

    connection.close()

    print()
    print("Monitor finished successfully.")


if __name__ == "__main__":
    main()
