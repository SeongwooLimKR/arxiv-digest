import os, json, smtplib, requests, re, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ── 탑티어 학회 목록 ──────────────────────────────────────────────────────
TOP_VENUES = {
    "NeurIPS", "ICML", "ICLR", "AAAI", "IJCAI", "AISTATS", "UAI", "ECML",
    "ACL", "EMNLP", "NAACL", "COLING", "EACL", "CoNLL",
    "CVPR", "ICCV", "ECCV", "WACV", "BMVC",
    "ICASSP", "Interspeech",
    "ICRA", "IROS", "RSS", "CoRL",
    "KDD", "WWW", "SIGIR", "WSDM", "RecSys", "CIKM",
    "MLSys", "OSDI", "SOSP", "EuroSys",
    "JMLR", "TACL", "TMLR", "TPAMI", "IJCV", "Nature", "Science",
}

# ── 요약 프롬프트 ─────────────────────────────────────────────────────────
SUMMARY_PROMPT = """학술 논문을 구조적으로 분석하여 핵심 내용을 한국어로 정리해줘.
모델명·데이터셋명·평가 지표·알고리즘명 등 전문 용어는 영어 원문 유지.
한국어로 번역 시 의미가 불명확한 개념은 한국어(영어) 형식으로 병기.
수식은 LaTeX 형식($...$, $$...$$)으로 그대로 작성해줘. 표는 마크다운 표 형식으로 작성해줘.

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
- 각 Step마다: 무엇을 하는지(목적) / 어떻게 하는지(구체적 방법, 수식) / 왜 이렇게 하는지(직관적 이유) 포함
- 모델 구조는 입력->처리->출력 흐름으로 추적
- 핵심 수식이 있으면 LaTeX로 작성하고 각 기호의 의미를 설명
- 독자가 이 섹션만 읽어도 방법론을 직접 구현할 수 있는 수준 목표

## 🧪 실험
- 데이터셋: 어떤 데이터로 실험했는지
- 평가 지표: 어떤 metric으로 측정했는지
- 성능 결과: 기존 방법 대비 수치 포함 (가능하면 마크다운 표로)

## 🔴 비판적 분석
균형 있는 시각으로 구체적 이유와 함께 서술:
- 실험의 한계 (설계, 데이터셋, 비교 대상)
- 방법론의 한계 (가정, 일반화, 계산 비용)
- 주장의 근거 충분성
- 향후 개선 방향

논문에 명시되지 않은 내용은 추측하지 말고 "논문에서 명확히 서술되지 않음"으로 표기.

---
논문 제목: {title}
저자: {authors}
초록: {abstract}"""

# ── State 관리 ────────────────────────────────────────────────────────────

def load_state() -> dict:
    with open("state.json", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: dict):
    with open("state.json", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── Semantic Scholar 논문 수집 ────────────────────────────────────────────

SS_FIELDS = "title,authors,abstract,year,venue,publicationVenue,externalIds"
SS_BASE   = "https://api.semanticscholar.org/graph/v1"

def _ss_to_paper(data: dict, source: str) -> dict | None:
    ext = data.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv")
    if not arxiv_id:
        return None
    authors = data.get("authors") or []
    venue = data.get("venue", "") or ""
    pub_venue = data.get("publicationVenue") or {}
    venue_name = pub_venue.get("name", venue) or venue
    return {
        "id": arxiv_id,
        "title": (data.get("title") or "").replace("\n", " ").strip(),
        "authors": ", ".join(a.get("name", "") for a in authors[:3]),
        "abstract": (data.get("abstract") or "")[:1500],
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "published": str(data.get("year") or ""),
        "keyword": source,
        "venue": venue_name.strip() if venue_name else None,
        "venue_year": data.get("year"),
    }

def fetch_seed_papers(seed_ids: list, exclude_ids: set) -> list:
    papers = []
    for arxiv_id in seed_ids:
        cid = arxiv_id.split("v")[0].strip()
        if cid in exclude_ids:
            continue
        try:
            resp = requests.get(f"{SS_BASE}/paper/arXiv:{cid}",
                                params={"fields": SS_FIELDS}, timeout=10)
            if resp.status_code == 200:
                p = _ss_to_paper(resp.json(), "시드 논문")
                if p:
                    papers.append(p)
                    exclude_ids.add(cid)
            time.sleep(0.3)
        except Exception:
            continue
    return papers

def fetch_citing_papers(seed_ids: list, exclude_ids: set, max_per_seed: int = 5) -> list:
    papers = []
    for arxiv_id in seed_ids:
        cid = arxiv_id.split("v")[0].strip()
        try:
            resp = requests.get(f"{SS_BASE}/paper/arXiv:{cid}/citations",
                                params={"fields": SS_FIELDS, "limit": 50}, timeout=10)
            if resp.status_code != 200:
                continue
            citations = sorted(
                resp.json().get("data", []),
                key=lambda x: x.get("citingPaper", {}).get("year") or 0,
                reverse=True,
            )
            count = 0
            for item in citations:
                p = _ss_to_paper(item.get("citingPaper", {}), f"인용 (arXiv:{cid})")
                if p and p["id"] not in exclude_ids:
                    papers.append(p)
                    exclude_ids.add(p["id"])
                    count += 1
                    if count >= max_per_seed:
                        break
            time.sleep(0.3)
        except Exception:
            continue
    return papers

def fetch_keyword_papers(keywords: list, exclude_ids: set, max_per_kw: int = 10) -> list:
    papers = []
    for kw in keywords:
        try:
            resp = requests.get(f"{SS_BASE}/paper/search",
                                params={"query": kw, "fields": SS_FIELDS,
                                        "limit": max_per_kw * 2}, timeout=10)
            if resp.status_code != 200:
                continue
            count = 0
            for item in resp.json().get("data", []):
                p = _ss_to_paper(item, kw)
                if p and p["id"] not in exclude_ids:
                    papers.append(p)
                    exclude_ids.add(p["id"])
                    count += 1
                    if count >= max_per_kw:
                        break
            time.sleep(0.3)
        except Exception:
            continue
    return papers

def fetch_all_papers(state: dict) -> list:
    exclude_ids = set(p.split("v")[0] for p in state.get("sent_papers", []))
    seed_ids    = state.get("seed_papers", [])
    keywords    = state.get("keywords", [])
    all_papers  = []

    if seed_ids:
        seeds = fetch_seed_papers(seed_ids, exclude_ids)
        print(f"  시드 논문: {len(seeds)}편")
        all_papers.extend(seeds)

    if seed_ids:
        citing = fetch_citing_papers(seed_ids, exclude_ids, max_per_seed=5)
        print(f"  인용 논문: {len(citing)}편")
        all_papers.extend(citing)

    if keywords:
        kw_papers = fetch_keyword_papers(keywords, exclude_ids, max_per_kw=8)
        print(f"  키워드 검색: {len(kw_papers)}편")
        all_papers.extend(kw_papers)

    print(f"  총 후보: {len(all_papers)}편")
    return all_papers

def is_top_venue(venue: str) -> bool:
    if not venue:
        return False
    v = venue.upper()
    return any(top.upper() in v for top in TOP_VENUES)


# ── 요약 생성 ─────────────────────────────────────────────────────────────

def summarize_paper(paper: dict) -> str:
    """7섹션 전체 요약 (MD 파일용)."""
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8192,
        messages=[{"role": "user", "content": SUMMARY_PROMPT.format(
            title=paper["title"],
            authors=paper["authors"],
            abstract=paper["abstract"],
        )}],
    )
    return msg.content[0].text

def _simple_md_to_html(text: str) -> str:
    """이메일 본문용 간단한 마크다운 → HTML 변환.
    수식($...$)은 텍스트로 유지, 나머지 서식만 처리."""
    lines = text.split("\n")
    html_parts = []
    in_ul = False

    for line in lines:
        s = line.strip()

        # 헤더 ### / ##
        if re.match(r'^#{2,3}\s+', s):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            content = re.sub(r'^#{2,3}\s*', '', s)
            content = _fmt_inline(content)
            html_parts.append(f'<p style="margin:10px 0 2px;font-weight:600;color:#1a1a2e">{content}</p>')

        # 불릿
        elif re.match(r'^[-*]\s+', s):
            if not in_ul:
                html_parts.append('<ul style="margin:4px 0 4px 18px;padding:0">')
                in_ul = True
            html_parts.append(f'<li style="margin:2px 0;line-height:1.7">{_fmt_inline(s[2:])}</li>')

        # 번호 리스트 / Step N
        elif re.match(r'^(\d+\.|Step\s*\d+)', s, re.IGNORECASE):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f'<p style="margin:3px 0 3px 8px;line-height:1.7">{_fmt_inline(s)}</p>')

        # 빈 줄
        elif not s:
            if in_ul: html_parts.append("</ul>"); in_ul = False

        # 일반 본문
        else:
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f'<p style="margin:4px 0;line-height:1.8">{_fmt_inline(s)}</p>')

    if in_ul:
        html_parts.append("</ul>")
    return "\n".join(html_parts)


def _fmt_inline(text: str) -> str:
    """인라인 서식: bold, italic, code 처리. 수식은 코드 스타일로 표시."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # **bold**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # *italic*
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # `code`
    text = re.sub(r'`(.+?)`',
                  r'<code style="background:#f0eeff;padding:1px 5px;border-radius:3px;font-size:12px">\1</code>',
                  text)
    # $$수식$$ → 코드 스타일
    text = re.sub(r'\$\$(.+?)\$\$',
                  r'<code style="background:#f5f5f5;padding:1px 5px;border-radius:3px;font-size:12px">\1</code>',
                  text, flags=re.DOTALL)
    # $수식$  → 코드 스타일
    text = re.sub(r'\$([^$\n]+?)\$',
                  r'<code style="background:#f5f5f5;padding:1px 5px;border-radius:3px;font-size:12px">\1</code>',
                  text)
    return text


def extract_goal_section(summary: str) -> str:
    """요약 텍스트에서 '목표 Task' 섹션 내용을 HTML로 변환해서 반환."""
    match = re.search(
        r'##\s*[🎯]?\s*목표\s*Task\s*\n([\s\S]+?)(?=\n##|\Z)',
        summary, re.IGNORECASE
    )
    if match:
        content = match.group(1).strip()
        # 너무 길면 600자로 자르기 (HTML 변환 전)
        if len(content) > 600:
            content = content[:600].rsplit(".", 1)[0] + "..."
        return _simple_md_to_html(content)
    return _simple_md_to_html(summary[:400].strip() + "...")


# ── MD 파일 생성 ──────────────────────────────────────────────────────────

def create_paper_html(paper: dict, summary: str) -> str:
    """논문 요약 HTML 생성 — MathJax(수식) + marked.js(마크다운) 렌더링."""
    venue_str = ""
    if paper.get("venue"):
        yr = f" {paper['venue_year']}" if paper.get("venue_year") else ""
        venue_str = f"<br><strong>학회:</strong> {paper['venue']}{yr}"

    # summary 안의 백틱을 JS 템플릿 리터럴과 충돌하지 않게 이스케이프
    summary_escaped = summary.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{paper['title']}</title>

<!-- MathJax: 수식 렌더링 -->
<script>
MathJax = {{
  tex: {{
    inlineMath: [['$', '$']],
    displayMath: [['$$', '$$']],
    processEscapes: true,
  }},
  options: {{ skipHtmlTags: ['script','noscript','style','textarea'] }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>

<!-- marked.js: 마크다운 → HTML -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 820px;
    margin: 40px auto;
    padding: 0 24px 60px;
    color: #1a1a2e;
    line-height: 1.75;
    background: #fff;
  }}
  h1 {{ font-size: 22px; font-weight: 600; border-bottom: 2px solid #7c5cbf; padding-bottom: 10px; }}
  h2 {{ font-size: 17px; font-weight: 600; color: #5a3ea8; margin-top: 32px; border-left: 4px solid #7c5cbf; padding-left: 10px; }}
  h3 {{ font-size: 15px; font-weight: 600; color: #333; margin-top: 20px; }}
  .meta {{ color: #888; font-size: 13px; margin: 8px 0 20px; }}
  .meta a {{ color: #7c5cbf; text-decoration: none; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 24px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }}
  th {{ background: #f0eeff; color: #5a3ea8; padding: 8px 12px; text-align: left; border: 1px solid #d4ccf5; }}
  td {{ padding: 7px 12px; border: 1px solid #e8e8e8; }}
  tr:nth-child(even) td {{ background: #faf9ff; }}
  code {{ background: #f0eeff; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-family: "SF Mono", Menlo, monospace; }}
  pre {{ background: #f6f5ff; border-radius: 6px; padding: 14px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 3px solid #d4ccf5; margin: 0; padding-left: 16px; color: #666; }}
  li {{ margin: 4px 0; }}
  .footer {{ color: #bbb; font-size: 11px; margin-top: 40px; border-top: 1px solid #eee; padding-top: 10px; }}
</style>
</head>
<body>

<h1 id="title"></h1>
<div class="meta" id="meta"></div>
<hr>
<div id="content"></div>
<div class="footer">생성일: {datetime.now().strftime('%Y-%m-%d')} | GitHub Actions + Claude API</div>

<script>
  // 제목·메타 삽입
  document.getElementById('title').textContent = {json.dumps(paper['title'])};
  document.getElementById('meta').innerHTML =
    '<strong>저자:</strong> {paper["authors"]} &nbsp;|&nbsp; '
    + '<strong>출판:</strong> {paper["published"]}'
    + '{venue_str}'
    + '<br><strong>arXiv:</strong> <a href="{paper["url"]}" target="_blank">{paper["url"]}</a>';

  // marked 설정 — GFM(표, 코드블록 등) 활성화
  marked.setOptions({{ gfm: true, breaks: true }});

  // 마크다운 → HTML 변환 후 삽입
  const raw = `{summary_escaped}`;
  document.getElementById('content').innerHTML = marked.parse(raw);

  // MathJax 재실행 (marked가 DOM 변경 후)
  if (window.MathJax) MathJax.typesetPromise();
</script>
</body>
</html>"""


# ── 이메일 빌드 ───────────────────────────────────────────────────────────

def build_email_html(papers: list, one_liners: list, keywords: list) -> str:
    date_str = datetime.now().strftime("%Y년 %m월 %d일")

    keyword_badges = "".join(
        f'<span style="display:inline-block;background:#eeeafc;color:#5a3ea8;'
        f'font-size:12px;padding:3px 10px;border-radius:12px;margin:3px 2px">'
        f'{kw}</span>'
        for kw in keywords
    )

    items = ""
    for i, (p, ol) in enumerate(zip(papers, one_liners), 1):
        venue_badge = ""
        if p.get("venue"):
            yr = f" {p['venue_year']}" if p.get("venue_year") else ""
            venue_badge = (
                f' <span style="background:#7c5cbf;color:#fff;font-size:11px;'
                f'padding:2px 8px;border-radius:10px">{p["venue"]}{yr}</span>'
            )

        # 출처 표시 (시드 논문 여부)
        source_tag = ""
        if p.get("keyword") == "시드 논문":
            source_tag = ' <span style="background:#e8f5e9;color:#2e7d32;font-size:11px;padding:2px 6px;border-radius:8px">시드</span>'
        elif p.get("keyword", "").startswith("인용"):
            source_tag = ' <span style="background:#e3f2fd;color:#1565c0;font-size:11px;padding:2px 6px;border-radius:8px">인용</span>'

        items += f"""
        <div style="border:1px solid #e8e4f5;border-radius:8px;padding:16px;margin:14px 0">
          <p style="margin:0 0 6px;font-size:15px;line-height:1.4">
            <strong>{i}. <a href="{p['url']}" style="color:#1a1a2e;text-decoration:none">{p['title']}</a></strong>
            {venue_badge}{source_tag}
          </p>
          <p style="margin:0 0 10px;color:#999;font-size:12px">
            {p['authors']} · {p['published']}
          </p>
          <p style="margin:0 0 8px;font-size:14px;line-height:1.7;color:#444">{ol}</p>
          <p style="margin:0;font-size:12px;color:#aaa">
            📎 상세 요약(수식·표 포함)은 첨부된 .html 파일을 브라우저로 열어보세요.
          </p>
        </div>"""

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;color:#333;padding:20px">
    <h2 style="color:#1a1a2e;border-bottom:2px solid #7c5cbf;padding-bottom:8px">
      📄 arXiv 논문 다이제스트 — {date_str}
    </h2>

    <div style="background:#f5f3ff;border:1px solid #d4ccf5;border-radius:6px;
    padding:12px 16px;margin-bottom:16px">
      <p style="margin:0 0 6px;font-size:12px;color:#7c5cbf;font-weight:bold">현재 관심 키워드</p>
      <div>{keyword_badges}</div>
    </div>

    <div style="background:#fffbea;border:1px solid #f0d080;border-radius:6px;
    padding:12px 16px;margin-bottom:20px;font-size:13px">
      오늘의 논문 <strong>{len(papers)}편</strong>입니다.
      각 논문의 <strong>상세 요약(수식·표·Step-by-step 방법론)</strong>은 첨부된 <code>.html</code> 파일을 브라우저로 열어보세요.<br><br>
      <strong>다 읽고 회신해주세요:</strong>
      <code style="background:#f0f0f0;padding:2px 6px;border-radius:3px">1: 관심있음 / 2: 보통 / 3: 관심없음</code>
      또는 <code style="background:#f0f0f0;padding:2px 6px;border-radius:3px">앞으로 RL 위주로 보내줘</code>
    </div>

    {items}

    <p style="color:#bbb;font-size:11px;margin-top:24px;border-top:1px solid #eee;padding-top:10px">
      GitHub Actions + Claude API로 자동 생성
    </p>
    </body></html>"""


def send_email(subject: str, html_body: str, attach_paths: list):
    """HTML 본문 + HTML 첨부파일 발송."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = os.environ["GMAIL_USER"]
    msg["To"]      = os.environ["TO_EMAIL"]

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    for path in attach_paths:
        with open(path, "rb") as f:
            part = MIMEBase("text", "html")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{Path(path).name}"')
        msg.attach(part)

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
        subprocess.run(["git", "commit", "-m", "chore: update state after digest"], check=True)
        subprocess.run(["git", "push"], check=True)


# ── 메인 ─────────────────────────────────────────────────────────────────

def main():
    import tempfile as _tf

    state = load_state()

    if state.get("waiting_for_feedback"):
        print("피드백 대기 중 — 발송 건너뜀")
        return

    batch_size = state.get("batch_size", 4)

    print("논문 수집 중...")
    candidates = fetch_all_papers(state)

    filtered = [p for p in candidates if is_top_venue(p.get("venue", ""))]
    print(f"  탑티어 학회 논문: {len(filtered)}편")

    # 탑티어 부족하면 시드 논문은 학회 무관 포함
    if len(filtered) < batch_size:
        seed_only = [p for p in candidates
                     if p.get("keyword") == "시드 논문" and p not in filtered]
        filtered = filtered + seed_only
        print(f"  시드 포함 후: {len(filtered)}편")

    if not filtered:
        print("새 논문 없음")
        return

    batch = filtered[:batch_size]
    print(f"\n{len(batch)}편 처리 시작...")

    one_liners   = []
    html_paths   = []

    with _tf.TemporaryDirectory() as tmpdir:
        for i, p in enumerate(batch, 1):
            venue_info = f"({p['venue']})" if p.get("venue") else "(학회 미확인)"
            print(f"  [{i}/{len(batch)}] {p['title'][:55]}... {venue_info}")

            # 전체 요약 생성
            summary   = summarize_paper(p)
            # 목표 Task 섹션 추출 (이메일 본문용)
            one_liner = extract_goal_section(summary)
            one_liners.append(one_liner)

            # HTML 파일 생성 (MathJax + marked.js)
            html_content = create_paper_html(p, summary)
            safe_title   = re.sub(r'[^\w\s-]', '', p['title'])[:45].strip()
            html_path    = os.path.join(tmpdir, f"{i:02d}_{safe_title}.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            html_paths.append(html_path)
            print(f"    HTML 생성 완료")

        email_html = build_email_html(batch, one_liners, state["keywords"])
        date_str   = datetime.now().strftime("%m/%d")
        venue_names = list({p["venue"] for p in batch if p.get("venue")})
        venue_str   = f" | {', '.join(venue_names)}" if venue_names else ""
        send_email(
            f"[arXiv 다이제스트] {date_str} — {len(batch)}편{venue_str}",
            email_html, html_paths,
        )

    print("\n이메일 발송 완료 (HTML 첨부)")

    state["sent_papers"]     = state.get("sent_papers", []) + [p["id"] for p in batch]
    state["pending_feedback"] = [{"id": p["id"], "title": p["title"]} for p in batch]
    state["waiting_for_feedback"] = True
    save_state(state)
    commit_state()


if __name__ == "__main__":
    main()
