import os, json, smtplib, feedparser, requests, re, tempfile, io
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
import anthropic

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    KeepTogether, Image as RLImage,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ── 탑티어 학회 목록 ──────────────────────────────────────────────────────
TOP_VENUES = {
    # AI/ML 일반
    "NeurIPS", "ICML", "ICLR", "AAAI", "IJCAI", "AISTATS", "UAI", "ECML",
    # NLP
    "ACL", "EMNLP", "NAACL", "COLING", "EACL", "CoNLL",
    # Computer Vision
    "CVPR", "ICCV", "ECCV", "WACV", "BMVC",
    # Multimodal / Speech
    "ICASSP", "Interspeech",
    # Robotics
    "ICRA", "IROS", "RSS", "CoRL",
    # Data Mining / IR / Web
    "KDD", "WWW", "SIGIR", "WSDM", "RecSys", "CIKM",
    # Systems / LLM 인프라
    "MLSys", "OSDI", "SOSP", "EuroSys",
    # 저널
    "JMLR", "TACL", "TMLR", "TPAMI", "IJCV", "Nature", "Science",
}

# ── 그림 선별 기준 ────────────────────────────────────────────────────────
# 최소 크기 (너무 작은 아이콘·로고 제외)
MIN_IMG_WIDTH  = 100   # px
MIN_IMG_HEIGHT = 80    # px
# 논문당 최대 선별 그림 수
MAX_FIGURES_PER_PAPER = 3

# ── 그림 선별 프롬프트 (캡션 + 본문 언급 맥락 활용) ─────────────────────
FIGURE_FILTER_PROMPT = """다음은 AI/ML 논문에서 추출한 그림 정보야.
각 항목에는 캡션(Figure 아래 설명)과 본문에서 해당 그림을 언급한 문장들이 있어.
이 두 가지를 함께 보고, 각 그림이 논문의 방법론이나 핵심 개념 이해에 핵심적으로 도움이 되는지 판단해줘.

선택 기준:
- 포함: 모델 아키텍처, 전체 파이프라인, 핵심 알고리즘 흐름, 주요 실험 결과 비교 그래프/표
- 제외: 단순 예시 이미지, 동기 부여용 배경 설명, 세부 ablation 결과, 데이터셋 샘플 이미지

판단 팁:
- 본문에서 "Figure N shows our proposed ...", "As shown in Figure N, the model ..." 처럼
  제안 방법을 직접 설명할 때 언급되면 핵심 그림일 가능성이 높음
- 본문 언급 횟수가 많을수록 중요한 그림

그림 정보:
{figure_info}

아래 JSON만 반환해줘. 설명 없이 JSON만.
{{"selected": [포함할 그림의 인덱스(0부터 시작) 배열]}}

최대 {max_count}개만 선택. 핵심적인 것이 없으면 빈 배열 반환."""

# ── 논문 요약 프롬프트 ────────────────────────────────────────────────────
SUMMARY_PROMPT = """학술 논문을 구조적으로 분석하여 핵심 내용을 한국어로 정리해줘.
모델명·데이터셋명·평가 지표·알고리즘명 등 전문 용어는 영어 원문 유지.
한국어로 번역 시 의미가 불명확한 개념은 한국어(영어) 형식으로 병기.

아래 7개 섹션을 순서대로 작성해:

## 목표 Task
이 논문이 풀고자 하는 문제와 왜 중요한지(motivation)를 서술.

## 기존 연구의 접근 방법
기존 방법론들의 핵심 아이디어를 한 줄씩 나열하고, 공통 한계를 정리.

## 배경지식
이 논문 이해에 필요한 사전 개념 설명. 불필요하면 섹션 생략.

## 제안 방법의 차별점
"기존에는 X였는데, 이 논문은 Y를 한다" 형식으로 대비해서 서술.

## 제안 방법의 구체적인 내용
Step-by-step으로 상세히 설명. 압축하지 말고 각 단계를 충분히 풀어서 서술.
- Step 1, Step 2, ... 형식으로 번호를 붙여 순서대로 설명
- 각 Step마다: 무엇을 하는지(목적) / 어떻게 하는지(구체적 방법, 수식) / 왜 이렇게 하는지(직관적 이유) 포함
- 모델 구조는 입력->처리->출력 흐름으로 추적
- 핵심 수식이 있으면 수식과 각 기호의 의미를 설명
- 독자가 이 섹션만 읽어도 방법론을 직접 구현할 수 있는 수준 목표

## 실험
- 데이터셋: 어떤 데이터로 실험했는지
- 평가 지표: 어떤 metric으로 측정했는지
- 성능 결과: 기존 방법 대비 수치 포함해서 서술

## 비판적 분석
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


# ── 논문 수집 ─────────────────────────────────────────────────────────────

def fetch_papers(keywords: list, max_per_kw: int, exclude_ids: list) -> list:
    papers = []
    seen_ids = set(exclude_ids)
    for kw in keywords:
        query = kw.replace(" ", "+")
        url = (
            f"http://export.arxiv.org/api/query"
            f"?search_query=all:{query}"
            f"&sortBy=submittedDate&sortOrder=descending&max_results=30"
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
                "venue": None,
                "venue_year": None,
            })
            seen_ids.add(pid)
            count += 1
            if count >= max_per_kw:
                break
    return papers


# ── 학회 필터링 ───────────────────────────────────────────────────────────

def get_venue_from_semantic_scholar(paper: dict) -> dict:
    try:
        arxiv_id = paper["id"].split("v")[0]
        url = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
        resp = requests.get(url, params={"fields": "venue,publicationVenue,year"}, timeout=8)
        if resp.status_code != 200:
            return paper
        data = resp.json()
        venue = data.get("venue", "") or ""
        pub_venue = data.get("publicationVenue") or {}
        venue_name = pub_venue.get("name", venue) or venue
        paper["venue"] = venue_name.strip() if venue_name else None
        paper["venue_year"] = data.get("year")
    except Exception:
        pass
    return paper

def is_top_venue(venue: str) -> bool:
    if not venue:
        return False
    v = venue.upper()
    return any(top.upper() in v for top in TOP_VENUES)

def enrich_and_filter_papers(papers: list, require_venue: bool = True) -> list:
    print(f"  {len(papers)}편 학회 정보 조회 중...")
    enriched = []
    for p in papers:
        p = get_venue_from_semantic_scholar(p)
        if is_top_venue(p.get("venue", "")):
            enriched.append(p)
        elif not require_venue and not p.get("venue"):
            enriched.append(p)
    print(f"  탑티어 학회 논문: {len(enriched)}편")
    return enriched


# ── 그림 추출 및 선별 ─────────────────────────────────────────────────────

def download_arxiv_pdf(arxiv_id: str, dest_path: str) -> bool:
    """arXiv PDF 다운로드. 성공 시 True."""
    pid = arxiv_id.split("v")[0]
    url = f"https://arxiv.org/pdf/{pid}.pdf"
    try:
        resp = requests.get(url, timeout=30, stream=True)
        if resp.status_code != 200:
            return False
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception:
        return False


def extract_figures_with_captions(pdf_path: str) -> list:
    """pymupdf로 PDF에서 그림 + 캡션 + 본문 언급 문장을 추출.
    반환: [{
        "index": int, "caption": str, "body_mentions": [str, ...],
        "image_bytes": bytes, "ext": str, "width": int, "height": int
    }, ...]
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        print("  pymupdf 없음 — 그림 추출 건너뜀")
        return []

    results = []
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []

    # 전체 텍스트 페이지별 수집
    page_texts = []
    for page in doc:
        page_texts.append(page.get_text("text"))

    # 전체 본문 텍스트 (본문 언급 검색용)
    full_text = "\n".join(page_texts)

    fig_index = 0
    for page_num, page in enumerate(doc):
        page_text = page_texts[page_num]

        img_list = page.get_images(full=True)
        for img_info in img_list:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            w, h = base_image["width"], base_image["height"]
            if w < MIN_IMG_WIDTH or h < MIN_IMG_HEIGHT:
                continue
            ratio = w / h if h > 0 else 0
            if ratio > 10 or ratio < 0.1:
                continue

            fig_num = fig_index + 1

            # 1. 캡션 추출 (그림 바로 아래 설명)
            caption = _find_caption_for_figure(page_text, fig_num)

            # 2. 본문 언급 문장 추출 (캡션 외 본문에서 해당 Figure를 인용한 문장들)
            body_mentions = _find_body_mentions(full_text, fig_num, caption)

            results.append({
                "index": fig_index,
                "caption": caption,
                "body_mentions": body_mentions,
                "image_bytes": base_image["image"],
                "ext": base_image["ext"],
                "width": w,
                "height": h,
            })
            fig_index += 1

    doc.close()
    return results


def _find_caption_for_figure(page_text: str, fig_num: int) -> str:
    """페이지 텍스트에서 Figure N 캡션 추출."""
    patterns = [
        rf"Figure\s+{fig_num}[:\.]?\s*(.{{10,300}})",
        rf"Fig\.\s*{fig_num}[:\.]?\s*(.{{10,300}})",
        rf"Fig\s+{fig_num}[:\.]?\s*(.{{10,300}})",
        rf"FIGURE\s+{fig_num}[:\.]?\s*(.{{10,300}})",
    ]
    for pat in patterns:
        m = re.search(pat, page_text, re.IGNORECASE | re.DOTALL)
        if m:
            caption = re.sub(r'\s+', ' ', m.group(1).strip())[:200]
            return caption
    return ""


def _find_body_mentions(full_text: str, fig_num: int, caption: str) -> list:
    """전체 본문에서 Figure N을 언급하는 문장을 추출.
    캡션 자체는 제외하고, 본문에서 인용되는 문장만 수집.
    최대 4문장 반환.
    """
    # Figure N 언급 패턴 (괄호 포함: (Figure 3), (Fig. 3) 등)
    patterns = [
        rf"[^.]*(?:Figure|Fig\.?)\s+{fig_num}[^.]*\.",
        rf"[^.]*\((?:Figure|Fig\.?)\s+{fig_num}\)[^.]*\.",
    ]

    mentions = []
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, full_text, re.IGNORECASE):
            sentence = re.sub(r'\s+', ' ', m.group(0).strip())
            # 캡션 자체와 중복 제거
            if caption and caption[:40] in sentence:
                continue
            # 너무 짧거나 이미 수집한 문장 제외
            if len(sentence) < 20 or sentence in seen:
                continue
            seen.add(sentence)
            mentions.append(sentence[:200])
            if len(mentions) >= 4:
                break
        if len(mentions) >= 4:
            break

    return mentions


def select_key_figures(figures: list, max_count: int = MAX_FIGURES_PER_PAPER) -> list:
    """캡션 + 본문 언급 맥락을 Claude에게 보내서 핵심 그림 선별."""
    if not figures:
        return []

    # 캡션이나 본문 언급이 하나라도 있는 것만 후보로
    candidates = [f for f in figures if f.get("caption") or f.get("body_mentions")]
    if not candidates:
        # 둘 다 없으면 크기 기준 상위 max_count개 반환
        return sorted(figures, key=lambda x: x["width"] * x["height"], reverse=True)[:max_count]

    # 각 그림의 캡션 + 본문 언급을 구조화해서 전달
    figure_info_parts = []
    for i, f in enumerate(candidates):
        parts = [f"[그림 {i}]"]

        if f.get("caption"):
            parts.append(f"  캡션: {f['caption']}")
        else:
            parts.append("  캡션: 없음")

        mentions = f.get("body_mentions", [])
        if mentions:
            parts.append(f"  본문 언급 ({len(mentions)}회):")
            for m in mentions:
                parts.append(f"    - {m}")
        else:
            parts.append("  본문 언급: 없음")

        figure_info_parts.append("\n".join(parts))

    figure_info_text = "\n\n".join(figure_info_parts)

    prompt = FIGURE_FILTER_PROMPT.format(
        figure_info=figure_info_text,
        max_count=max_count,
    )

    try:
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        result = json.loads(raw)
        selected_indices = result.get("selected", [])
        return [candidates[i] for i in selected_indices if i < len(candidates)]
    except Exception as e:
        print(f"  그림 선별 오류: {e} — 크기 기준으로 폴백")
        return sorted(candidates, key=lambda x: x["width"] * x["height"], reverse=True)[:max_count]


def get_key_figures(paper: dict, tmpdir: str) -> list:
    """PDF 다운로드 → 그림 추출 → 캡션 기반 선별 → 선별된 그림 반환."""
    pdf_path = os.path.join(tmpdir, f"{paper['id'].replace('/', '_')}.pdf")

    print(f"    PDF 다운로드 중...")
    if not download_arxiv_pdf(paper["id"], pdf_path):
        print(f"    PDF 다운로드 실패 — 그림 없이 진행")
        return []

    figures = extract_figures_with_captions(pdf_path)
    print(f"    그림 {len(figures)}개 발견")

    if not figures:
        return []

    selected = select_key_figures(figures, MAX_FIGURES_PER_PAPER)
    print(f"    핵심 그림 {len(selected)}개 선별됨")

    # 선별된 그림을 tmpdir에 이미지 파일로 저장
    saved = []
    for i, fig in enumerate(selected):
        ext = fig["ext"] if fig["ext"] in ("png", "jpeg", "jpg") else "png"
        img_path = os.path.join(tmpdir, f"{paper['id'].replace('/', '_')}_fig{i}.{ext}")
        with open(img_path, "wb") as f:
            f.write(fig["image_bytes"])
        saved.append({
            "path": img_path,
            "caption": fig["caption"],
            "width": fig["width"],
            "height": fig["height"],
        })

    return saved


# ── 요약 생성 ─────────────────────────────────────────────────────────────

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


# ── PDF 생성 ──────────────────────────────────────────────────────────────

def _register_korean_font():
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleGothic.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("KoreanFont", path))
                return "KoreanFont"
            except Exception:
                continue
    return "Helvetica"


def create_paper_pdf(paper: dict, summary: str, figures: list, output_path: str):
    """논문 요약 PDF 생성. figures는 get_key_figures() 반환값."""
    font_name = _register_korean_font()

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )

    # 스타일
    PAGE_W = A4[0] - 40*mm  # 본문 유효 너비

    style_title  = ParagraphStyle("T",  fontName=font_name, fontSize=15, leading=22,
                                   textColor=colors.HexColor("#1a1a2e"), spaceAfter=6)
    style_meta   = ParagraphStyle("M",  fontName=font_name, fontSize=10,
                                   textColor=colors.HexColor("#888888"), spaceAfter=4)
    style_venue  = ParagraphStyle("V",  fontName=font_name, fontSize=11,
                                   textColor=colors.HexColor("#7c5cbf"), spaceAfter=10)
    style_sec    = ParagraphStyle("S",  fontName=font_name, fontSize=13, leading=18,
                                   textColor=colors.HexColor("#1a1a2e"), spaceBefore=14, spaceAfter=4)
    style_body   = ParagraphStyle("B",  fontName=font_name, fontSize=11, leading=17,
                                   textColor=colors.HexColor("#333333"), spaceAfter=4)
    style_blt    = ParagraphStyle("BL", fontName=font_name, fontSize=11, leading=16,
                                   leftIndent=12, textColor=colors.HexColor("#444444"), spaceAfter=2)
    style_cap    = ParagraphStyle("C",  fontName=font_name, fontSize=9, leading=13,
                                   textColor=colors.HexColor("#666666"), alignment=1,  # 가운데 정렬
                                   spaceAfter=8)

    story = []

    # ── 헤더 ──
    venue_str = ""
    if paper.get("venue"):
        yr = f" {paper['venue_year']}" if paper.get("venue_year") else ""
        venue_str = f"{paper['venue']}{yr}"

    story.append(Paragraph(paper["title"], style_title))
    story.append(Paragraph(f"{paper['authors']}  |  {paper['published']}", style_meta))
    if venue_str:
        story.append(Paragraph(f"학회: {venue_str}", style_venue))
    story.append(Paragraph(f"arXiv: {paper['url']}  |  키워드: {paper['keyword']}", style_meta))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#7c5cbf"), spaceAfter=10))

    # ── 핵심 그림 삽입 (있을 경우) ──
    if figures:
        story.append(Paragraph("<b>핵심 그림</b>", style_sec))
        for fig in figures:
            try:
                # 이미지를 A4 본문 너비에 맞게 비율 유지하며 축소
                img_w_pt = fig["width"]
                img_h_pt = fig["height"]
                scale = min(PAGE_W / img_w_pt, 160*mm / img_h_pt, 1.0)
                display_w = img_w_pt * scale
                display_h = img_h_pt * scale

                rl_img = RLImage(fig["path"], width=display_w, height=display_h)
                caption_text = fig["caption"] if fig["caption"] else ""

                story.append(KeepTogether([
                    Spacer(1, 4*mm),
                    rl_img,
                    Paragraph(caption_text, style_cap) if caption_text else Spacer(1, 2*mm),
                ]))
            except Exception as e:
                print(f"    그림 삽입 오류: {e}")
                continue

        story.append(HRFlowable(width="100%", thickness=0.5,
                                 color=colors.HexColor("#dddddd"), spaceAfter=6))

    # ── 요약 본문 파싱 ──
    pending_body = []
    pending_blt  = []

    def flush():
        for ln in pending_body:
            story.append(Paragraph(ln, style_body))
        for bl in pending_blt:
            story.append(Paragraph(f"• {bl}", style_blt))
        pending_body.clear()
        pending_blt.clear()

    for line in summary.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            flush()
            header = re.sub(r'^##\s*', '', line).strip()
            story.append(KeepTogether([
                HRFlowable(width="100%", thickness=0.5,
                           color=colors.HexColor("#dddddd"), spaceBefore=8),
                Paragraph(f"<b>{header}</b>", style_sec),
            ]))
        elif line.startswith("- ") or line.startswith("* "):
            if pending_body:
                flush()
            pending_blt.append(line[2:])
        elif line:
            if pending_blt:
                flush()
            pending_body.append(line)

    flush()

    # ── 푸터 ──
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#eeeeee")))
    story.append(Paragraph(
        f"생성일: {datetime.now().strftime('%Y-%m-%d')}  |  GitHub Actions + Claude API",
        style_meta
    ))

    doc.build(story)


# ── 이메일 ────────────────────────────────────────────────────────────────

def build_email_html(papers: list, summaries: list, figures_per_paper: list, keywords: list) -> str:
    date_str = datetime.now().strftime("%Y년 %m월 %d일")

    # 키워드 배지 목록
    keyword_badges = "".join(
        f'<span style="display:inline-block;background:#eeeafc;color:#5a3ea8;'
        f'font-size:12px;padding:3px 10px;border-radius:12px;margin:3px 3px 3px 0">'
        f'{kw}</span>'
        for kw in keywords
    )
    keyword_section = f"""
    <div style="background:#f5f3ff;border:1px solid #d4ccf5;border-radius:6px;
    padding:12px 16px;margin-bottom:20px;">
      <p style="margin:0 0 8px;font-size:12px;color:#7c5cbf;font-weight:bold">
        현재 관심 키워드
      </p>
      <div>{keyword_badges}</div>
      <p style="margin:8px 0 0;font-size:11px;color:#aaa">
        키워드를 변경하려면 이 메일에 회신하세요. 예: <code>앞으로는 RLHF, alignment 위주로 보내줘</code>
      </p>
    </div>"""

    items = ""
    for i, (p, s, figs) in enumerate(zip(papers, summaries, figures_per_paper), 1):
        venue_badge = ""
        if p.get("venue"):
            yr = f" {p['venue_year']}" if p.get("venue_year") else ""
            venue_badge = (
                f'<span style="background:#7c5cbf;color:#fff;font-size:11px;'
                f'padding:2px 8px;border-radius:10px;margin-left:8px">'
                f'{p["venue"]}{yr}</span>'
            )
        fig_note = (
            f'<span style="color:#2a9d8f;font-size:12px"> · 핵심 그림 {len(figs)}개 포함</span>'
            if figs else ""
        )
        summary_html = (
            s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace("\n## ", "<br><br><strong>")
             .replace("\n- ", "<br>• ")
             .replace("\n", "<br>")
        )
        items += f"""
        <div style="background:#f8f9fa;border-left:4px solid #7c5cbf;
                    padding:18px;margin:20px 0;border-radius:6px;">
          <p style="margin:0 0 4px;font-size:16px">
            <strong>{i}. <a href="{p['url']}" style="color:#1a1a2e;text-decoration:none"
            >{p['title']}</a></strong>{venue_badge}
          </p>
          <p style="margin:0 0 14px;color:#888;font-size:12px">
            {p['authors']} · {p['published']} · 검색 키워드: <code>{p['keyword']}</code>
          </p>
          <div style="font-size:14px;line-height:1.8;color:#333">{summary_html}</div>
          <p style="margin:10px 0 0;font-size:12px;color:#999">
            PDF 첨부파일 포함{fig_note}
          </p>
        </div>"""

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:740px;
    margin:auto;color:#333;padding:20px">
    <h2 style="color:#1a1a2e;border-bottom:3px solid #7c5cbf;padding-bottom:10px">
      arXiv 논문 다이제스트 — {date_str}
    </h2>
    {keyword_section}
    <div style="background:#fffbea;border:1px solid #f0d080;border-radius:6px;
    padding:14px;margin-bottom:24px;font-size:14px">
      오늘의 논문 <strong>{len(papers)}편</strong>입니다 (탑티어 학회 우선 선별).<br>
      PDF 첨부파일에 핵심 그림이 포함되어 있습니다.<br><br>
      <strong>회신 형식:</strong><br>
      • 번호별 평가: <code>1: 관심있음 / 2: 보통 / 3: 관심없음</code><br>
      • 주제 변경: <code>앞으로는 RL이나 RLHF 관련 논문 위주로 보내줘</code>
    </div>
    {items}
    <p style="color:#aaa;font-size:12px;margin-top:30px;
    border-top:1px solid #eee;padding-top:12px">
      이 메일은 GitHub Actions + Claude API로 자동 생성되었습니다.
    </p></body></html>"""


def send_email(subject: str, html_body: str, pdf_paths: list):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = os.environ["TO_EMAIL"]

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    for pdf_path in pdf_paths:
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{Path(pdf_path).name}"')
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
        subprocess.run(["git", "commit", "-m", "chore: update state after sending digest"], check=True)
        subprocess.run(["git", "push"], check=True)


# ── 메인 ─────────────────────────────────────────────────────────────────

def main():
    state = load_state()

    if state.get("waiting_for_feedback"):
        print("피드백 대기 중 — 새 배치 발송 건너뜀")
        return

    batch_size = state.get("batch_size", 4)

    raw_papers = fetch_papers(
        state["keywords"], max_per_kw=10,
        exclude_ids=state.get("sent_papers", []),
    )

    filtered = enrich_and_filter_papers(raw_papers, require_venue=True)
    if len(filtered) < batch_size:
        print(f"  탑티어 논문 부족({len(filtered)}편) — 최신 논문으로 보완")
        filtered = enrich_and_filter_papers(raw_papers, require_venue=False)

    if not filtered:
        print("새 논문 없음")
        return

    batch = filtered[:batch_size]
    print(f"\n{len(batch)}편 처리 시작...")

    summaries = []
    pdf_paths = []
    figures_per_paper = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, p in enumerate(batch, 1):
            venue_info = f"({p['venue']})" if p.get("venue") else "(학회 미확인)"
            print(f"\n  [{i}/{len(batch)}] {p['title'][:55]}... {venue_info}")

            # 1. 요약 생성
            summary = summarize_paper(p)
            summaries.append(summary)

            # 2. PDF에서 핵심 그림 추출
            figures = get_key_figures(p, tmpdir)
            figures_per_paper.append(figures)

            # 3. 요약 PDF 생성 (그림 포함)
            safe_title = re.sub(r'[^\w\s-]', '', p['title'])[:40].strip()
            pdf_path = os.path.join(tmpdir, f"{i:02d}_{safe_title}.pdf")
            create_paper_pdf(p, summary, figures, pdf_path)
            pdf_paths.append(pdf_path)
            print(f"    PDF 생성 완료 (그림 {len(figures)}개 포함)")

        # 4. 이메일 발송
        html = build_email_html(batch, summaries, figures_per_paper, state["keywords"])
        date_str = datetime.now().strftime("%m/%d")
        venue_names = list({p["venue"] for p in batch if p.get("venue")})
        venue_str = f" | {', '.join(venue_names)}" if venue_names else ""
        send_email(
            f"[arXiv 다이제스트] {date_str} — {len(batch)}편{venue_str}",
            html, pdf_paths,
        )

    print("\n이메일 발송 완료 (PDF + 핵심 그림 첨부)")

    state["sent_papers"] = state.get("sent_papers", []) + [p["id"] for p in batch]
    state["pending_feedback"] = [{"id": p["id"], "title": p["title"]} for p in batch]
    state["waiting_for_feedback"] = True
    save_state(state)
    commit_state()


if __name__ == "__main__":
    main()
