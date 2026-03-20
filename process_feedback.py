import os, json, base64, subprocess
from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

FEEDBACK_PROMPT = """사용자가 arXiv 논문 다이제스트 이메일에 회신했습니다.

현재 관심 키워드: {keywords}
이번에 보낸 논문 목록:
{papers}

사용자 회신 내용:
{reply}

위 내용을 분석해서 아래 JSON만 반환해줘. 설명이나 마크다운 없이 JSON만.
{{
  "paper_ratings": {{
    "논문 제목": "관심있음 또는 보통 또는 관심없음"
  }},
  "new_keywords": ["업데이트된 키워드 배열"],
  "changes_made": "변경 사항 한 줄 요약",
  "next_batch_note": "다음 배치에 반영할 사항 (없으면 빈 문자열)"
}}

규칙:
- 숫자로 답했으면: 1=관심있음, 2=보통, 3=관심없음
- 키워드 변경 언급 없으면 new_keywords는 기존 그대로 유지
- 새 주제 추가 요청이면 new_keywords에 추가
- 특정 주제 제거 요청이면 new_keywords에서 삭제
- 키워드는 영어로, 구체적으로 (예: "RL" 대신 "reinforcement learning")"""


def load_state() -> dict:
    with open("state.json", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict):
    with open("state.json", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_gmail_service():
    creds_json = json.loads(os.environ["GMAIL_CREDENTIALS"])
    creds = Credentials.from_authorized_user_info(creds_json)
    return build("gmail", "v1", credentials=creds)


def get_body_text(payload: dict) -> str:
    """이메일 payload에서 텍스트 본문 추출"""
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        # text/plain 없으면 재귀로 parts 탐색
        for part in payload["parts"]:
            text = get_body_text(part)
            if text:
                return text
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return ""


def find_latest_digest_reply(service) -> tuple:
    """가장 최근 다이제스트 회신 스레드에서 사용자 회신 찾기.
    Returns (reply_text, message_id) or (None, None)
    """
    results = service.users().threads().list(
        userId="me",
        q='subject:"[arXiv 다이제스트]"',
        maxResults=5,
    ).execute()

    threads = results.get("threads", [])
    for thread_meta in threads:
        thread = service.users().threads().get(
            userId="me", id=thread_meta["id"], format="full"
        ).execute()
        messages = thread.get("messages", [])
        # 스레드에 2개 이상 메시지 = 회신 있음
        if len(messages) < 2:
            continue
        # 마지막 메시지가 회신 (내가 보낸 게 아닌 것)
        reply_msg = messages[-1]
        headers = {h["name"]: h["value"] for h in reply_msg["payload"]["headers"]}
        from_addr = headers.get("From", "")
        my_addr = os.environ.get("GMAIL_USER", "")
        if my_addr.lower() in from_addr.lower():
            continue  # 내가 보낸 메시지면 스킵
        body = get_body_text(reply_msg["payload"])
        if body.strip():
            return body.strip(), reply_msg["id"]
    return None, None


def parse_feedback(state: dict, reply: str) -> dict:
    papers_str = "\n".join(
        f"- {p['title']}" for p in state.get("pending_feedback", [])
    )
    prompt = FEEDBACK_PROMPT.format(
        keywords=state["keywords"],
        papers=papers_str,
        reply=reply,
    )
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # 혹시 마크다운 코드블록으로 감싸져 있으면 제거
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def commit_state():
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name", "GitHub Actions"], check=True)
    subprocess.run(["git", "add", "state.json"], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode != 0:
        subprocess.run(["git", "commit", "-m", "chore: update state from user feedback"], check=True)
        subprocess.run(["git", "push"], check=True)


def main():
    state = load_state()

    if not state.get("waiting_for_feedback"):
        print("피드백 대기 상태 아님 — 건너뜀")
        return

    print("📨 Gmail에서 회신 확인 중...")
    service = get_gmail_service()
    reply, msg_id = find_latest_digest_reply(service)

    if not reply:
        print("새 회신 없음")
        return

    # 이미 처리한 메시지인지 확인
    processed_ids = state.get("processed_message_ids", [])
    if msg_id in processed_ids:
        print("이미 처리한 회신 — 건너뜀")
        return

    print(f"📨 회신 발견 (길이: {len(reply)}자)")
    print(f"회신 내용 미리보기: {reply[:200]}...")

    result = parse_feedback(state, reply)
    print(f"📊 분석 결과: {result['changes_made']}")

    # state 업데이트
    state["keywords"] = result["new_keywords"]
    state["feedback_history"] = state.get("feedback_history", []) + [{
        "date": datetime.now().isoformat(),
        "reply_preview": reply[:300],
        "ratings": result["paper_ratings"],
        "changes_made": result["changes_made"],
        "next_batch_note": result.get("next_batch_note", ""),
    }]
    state["pending_feedback"] = []
    state["waiting_for_feedback"] = False
    state["processed_message_ids"] = processed_ids + [msg_id]
    # 처리된 ID 목록은 최근 50개만 유지
    state["processed_message_ids"] = state["processed_message_ids"][-50:]

    save_state(state)
    commit_state()
    print(f"✅ 완료 — 업데이트된 키워드: {state['keywords']}")


if __name__ == "__main__":
    main()
