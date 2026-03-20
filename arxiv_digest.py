import os, json, smtplib, feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ── 논문 요약 프롬프트 (paper-summary 스킬 기반) ──────────────────────────
SUMMARY_PROMPT = """학술 논문을 구조적으로 분석하여 핵심 내용을 한국어로 정리해줘.
모델명·데이터셋명·평가 지표·알고리즘명 등 전문 용어는 영어 원문 유지.
한국어로 번역 시 의미가 불명확한 개념은 한국어(영어) 형식으로 병기.

아래 7개 섹션을 순서대로 작성해:

## 🎯 목표 Task
이 논문이 풀고자 하는 문제와 왜 중요한지(motivation)를 서술.

## 🔍 기존 연구의 접근 방법
기존 방법론들의 핵심 아이디어를 한 줄씩 나열하고, 공통 한계를 정리.

## 📚 배경지식
이 논문 이해에 필요한 사전 개념 설명. 불필요하면 섹션 생략.

## ✨ 제안 방법의 차별점
"기존에는 X였는데, 이 논문은 Y를 한다" 형식으로 대비해서 서술.

## 🛠️ 제안 방법의 구체적인 내용
Step-by-step으로 상세히 설명. 압축하지 말고 각 단계를 충분히 풀어서 서술.
- Step 1, Step 2, ... 형식으로 번호를 붙여 순서대로 설명
- 각 Step마다: 무엇을 하는지(목적) / 어떻게 하는지(구체적 방법·수식) / 왜 이렇게 하는지(직관적 이유) 포함
- 모델 구조는 입력→처리→출력 흐름으로 추적
- 핵심 수식이 있으면 수식과 각 기호의 의미를 설명
- 독자가 이 섹션만 읽어도 방법론을 직접 구현할 수 있는 수준 목표

## 🧪 실험
- 데이터셋: 어떤 데이터로 실험했는지
- 평가 지표: 어떤 metric으로 측정했는지
- 성능 결과: 기존 방법 대비 수치 포함해서 서술

## 🔴 비판적 분석
균형 있는 시각으로 구체적 이유와 함께 서술:
- 실험의 한계 (설계·데이터셋·비교 대상)
- 방법론의 한계 (가정·일반화·계산 비용)
- 주장의 근거 충분성
- 향후 개선 방향

논문에 명시되지 않은 내용은 추측하지 말고 "논문에서 명확히 서술되지 않음"으로 표기.

---
논문 제목: {title}
저자: {authors}
초록: {abstract}"""


def load_state() -> dict:
    with open("state.json", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict):
    with open("state.json", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_papers(keywords: list, max_per_kw: int, exclude_ids: list) -> list:
    papers = []
    seen_ids = set(exclude_ids)
    for kw in keywords:
        query = kw.replace(" ", "+")
        url = (
            f"http://export.arxiv.org/api/query"
            f"?search_query=all:{query}"
            f"&sortBy=submittedDate&sortOrder=descending&max_results=20"
        )
        feed = feedparser.parse(url)
        count = 0
        for entry in feed.entries:
            pid = entry.id.split("/abs/")[-1]
            if pid in seen_ids:
                continue
            papers.append({
                "id": pid,
                "title": entry.title.replace("\n", " ").strip(),
                "authors": ", ".join(a.name for a in entry.authors[:3]),
                "abstract": entry.summary[:1500],
                "url": entry.link,
                "published": entry.published[:10],
                "keyword": kw,
            })
            seen_ids.add(pid)
            count += 1
            if count >= max_per_kw:
                break
    return papers


def summarize_paper(paper: dict) -> str:
    prompt = SUMMARY_PROMPT.format(
        title=paper["title"],
        authors=paper["authors"],
        abstract=paper["abstract"],
    )
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def build_email_html(papers: list, summaries: list) -> str:
    date_str = datetime.now().strftime("%Y년 %m월 %d일")
    items = ""
    for i, (p, s) in enumerate(zip(papers, summaries), 1):
        summary_html = (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\n## ", "<br><br><strong>")
             .replace("\n- ", "<br>• ")
             .replace("\n", "<br>")
        )
        items += f"""
        <div style="background:#f8f9fa;border-left:4px solid #7c5cbf;
                    padding:18px;margin:20px 0;border-radius:6px;">
          <p style="margin:0 0 4px;font-size:16px">
            <strong>{i}. <a href="{p['url']}" style="color:#1a1a2e;text-decoration:none">{p['title']}</a></strong>
          </p>
          <p style="margin:0 0 14px;color:#888;font-size:12px">
            {p['authors']} · {p['published']} · 키워드: <code>{p['keyword']}</code>
          </p>
          <div style="font-size:14px;line-height:1.8;color:#333">{summary_html}</div>
        </div>"""

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:740px;margin:auto;color:#333;padding:20px">
    <h2 style="color:#1a1a2e;border-bottom:3px solid #7c5cbf;padding-bottom:10px">
      📄 arXiv 논문 다이제스트 — {date_str}
    </h2>
    <div style="background:#fffbea;border:1px solid #f0d080;border-radius:6px;padding:14px;margin-bottom:24px;font-size:14px">
      오늘의 논문 <strong>{len(papers)}편</strong>입니다. 다 읽고 나서 <strong>이 메일에 회신</strong>해주세요.<br><br>
      <strong>회신 형식 (자유롭게 쓰셔도 됩니다):</strong><br>
      • 번호별 평가: <code>1: 관심있음 / 2: 보통 / 3: 관심없음</code><br>
      • 주제 변경: <code>앞으로는 RL이나 RLHF 관련 논문 위주로 보내줘</code><br>
      • 추가 요청: <code>survey 논문은 빼줘</code>
    </div>
    {items}
    <p style="color:#aaa;font-size:12px;margin-top:30px;border-top:1px solid #eee;padding-top:12px">
      이 메일은 GitHub Actions + Claude API로 자동 생성되었습니다.
    </p>
    </body></html>"""


def send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = os.environ["TO_EMAIL"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)


def commit_state():
    import subprocess
    subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
    subprocess.run(["git", "config", "user.name", "GitHub Actions"], check=True)
    subprocess.run(["git", "add", "state.json"], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode != 0:
        subprocess.run(["git", "commit", "-m", "chore: update state after sending digest"], check=True)
        subprocess.run(["git", "push"], check=True)


def main():
    state = load_state()

    if state.get("waiting_for_feedback"):
        print("⏳ 피드백 대기 중 — 새 배치 발송 건너뜀")
        return

    batch_size = state.get("batch_size", 4)
    papers = fetch_papers(
        state["keywords"],
        max_per_kw=6,
        exclude_ids=state.get("sent_papers", []),
    )

    if not papers:
        print("⚠️  새 논문 없음")
        return

    batch = papers[:batch_size]
    print(f"📥 {len(batch)}편 요약 시작...")

    summaries = []
    for p in batch:
        print(f"  🤖 요약 중: {p['title'][:60]}...")
        summaries.append(summarize_paper(p))

    html = build_email_html(batch, summaries)
    date_str = datetime.now().strftime("%m/%d")
    send_email(f"[arXiv 다이제스트] {date_str} — {len(batch)}편", html)
    print("✅ 이메일 발송 완료")

    state["sent_papers"] = state.get("sent_papers", []) + [p["id"] for p in batch]
    state["pending_feedback"] = [{"id": p["id"], "title": p["title"]} for p in batch]
    state["waiting_for_feedback"] = True
    save_state(state)
    commit_state()


if __name__ == "__main__":
    main()
