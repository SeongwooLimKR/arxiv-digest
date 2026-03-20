#!/bin/bash
# ============================================================
#  arXiv Digest — 원클릭 GitHub 세팅 스크립트
#  실행 전 필요한 것: git, GitHub CLI(gh), python3, pip
# ============================================================

set -e  # 에러 발생 시 즉시 중단

REPO_NAME="arxiv-digest"
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   arXiv Digest 자동 세팅 시작         ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ── 0. 의존성 확인 ───────────────────────────────────────────
echo -e "${YELLOW}[0/6] 의존성 확인 중...${NC}"

if ! command -v gh &> /dev/null; then
  echo -e "${RED}❌ GitHub CLI(gh)가 없습니다.${NC}"
  echo "설치: https://cli.github.com/"
  echo "  macOS:   brew install gh"
  echo "  Ubuntu:  sudo apt install gh"
  exit 1
fi

if ! command -v python3 &> /dev/null; then
  echo -e "${RED}❌ python3가 없습니다.${NC}"
  exit 1
fi

echo -e "${GREEN}✅ 의존성 확인 완료${NC}"

# ── 1. GitHub 로그인 확인 ────────────────────────────────────
echo ""
echo -e "${YELLOW}[1/6] GitHub 로그인 확인 중...${NC}"

if ! gh auth status &> /dev/null; then
  echo "GitHub에 로그인합니다..."
  gh auth login
fi

GITHUB_USER=$(gh api user --jq '.login')
echo -e "${GREEN}✅ 로그인됨: @${GITHUB_USER}${NC}"

# ── 2. GitHub 레포 생성 ──────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/6] GitHub 레포 생성 중...${NC}"

if gh repo view "${GITHUB_USER}/${REPO_NAME}" &> /dev/null; then
  echo -e "${YELLOW}⚠️  레포 '${REPO_NAME}'가 이미 존재합니다. 기존 레포를 사용합니다.${NC}"
else
  gh repo create "${REPO_NAME}" --private --description "arXiv 논문 자동 다이제스트"
  echo -e "${GREEN}✅ 레포 생성 완료: github.com/${GITHUB_USER}/${REPO_NAME}${NC}"
fi

# ── 3. 코드 푸시 ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/6] 코드 푸시 중...${NC}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "${SCRIPT_DIR}/.git" ]; then
  cd "${SCRIPT_DIR}"
  git init
  git add .
  git commit -m "init: arXiv digest system"
  git branch -M main
  git remote add origin "https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
  git push -u origin main
  echo -e "${GREEN}✅ 코드 푸시 완료${NC}"
else
  cd "${SCRIPT_DIR}"
  git add .
  git diff --cached --quiet || git commit -m "chore: update files"
  git push
  echo -e "${GREEN}✅ 코드 업데이트 완료${NC}"
fi

# ── 4. Secrets 등록 ──────────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/6] GitHub Secrets 등록${NC}"
echo "각 값을 입력해주세요. 입력값은 화면에 표시되지 않습니다."
echo ""

cd "${SCRIPT_DIR}"

# ANTHROPIC_API_KEY
echo -n "🔑 Anthropic API Key (sk-ant-...): "
read -s ANTHROPIC_KEY
echo ""
gh secret set ANTHROPIC_API_KEY --body "${ANTHROPIC_KEY}" --repo "${GITHUB_USER}/${REPO_NAME}"
echo -e "${GREEN}   ✅ ANTHROPIC_API_KEY 등록됨${NC}"

# GMAIL_USER
echo -n "📧 발송용 Gmail 주소: "
read GMAIL_USER_INPUT
gh secret set GMAIL_USER --body "${GMAIL_USER_INPUT}" --repo "${GITHUB_USER}/${REPO_NAME}"
echo -e "${GREEN}   ✅ GMAIL_USER 등록됨${NC}"

# GMAIL_APP_PASSWORD
echo ""
echo -e "${YELLOW}   📌 Gmail 앱 비밀번호 발급 방법:${NC}"
echo "   1. Google 계정 → 보안 → 2단계 인증 활성화"
echo "   2. 보안 → 앱 비밀번호 → 앱 선택: 메일, 기기: 기타"
echo "   3. 생성된 16자리 코드 입력"
echo ""
echo -n "🔑 Gmail 앱 비밀번호 (xxxx-xxxx-xxxx-xxxx): "
read -s APP_PASS
echo ""
gh secret set GMAIL_APP_PASSWORD --body "${APP_PASS}" --repo "${GITHUB_USER}/${REPO_NAME}"
echo -e "${GREEN}   ✅ GMAIL_APP_PASSWORD 등록됨${NC}"

# TO_EMAIL
echo -n "📬 논문을 받을 이메일 주소: "
read TO_EMAIL_INPUT
gh secret set TO_EMAIL --body "${TO_EMAIL_INPUT}" --repo "${GITHUB_USER}/${REPO_NAME}"
echo -e "${GREEN}   ✅ TO_EMAIL 등록됨${NC}"

# ── 5. Gmail OAuth 토큰 발급 ─────────────────────────────────
echo ""
echo -e "${YELLOW}[5/6] Gmail OAuth 토큰 발급 (회신 읽기용)${NC}"
echo ""
echo -e "${YELLOW}   📌 Google Cloud Console 설정 방법:${NC}"
echo "   1. https://console.cloud.google.com 접속"
echo "   2. 새 프로젝트 생성 (이름: arxiv-digest)"
echo "   3. APIs & Services → Gmail API 활성화"
echo "   4. OAuth 동의 화면 → 외부 → 앱 이름 입력 → 저장"
echo "   5. 사용자 인증 정보 → OAuth 2.0 클라이언트 ID 만들기"
echo "      → 애플리케이션 유형: 데스크톱 앱"
echo "   6. credentials.json 다운로드"
echo ""
echo -n "   credentials.json 파일 경로를 입력하세요: "
read CREDS_PATH

if [ ! -f "${CREDS_PATH}" ]; then
  echo -e "${RED}❌ 파일을 찾을 수 없습니다: ${CREDS_PATH}${NC}"
  echo "나중에 수동으로 등록하려면:"
  echo "  python3 get_gmail_token.py  (credentials.json을 같은 폴더에 두고 실행)"
  echo "  출력된 JSON을 GitHub Secret 'GMAIL_CREDENTIALS'에 등록"
else
  cp "${CREDS_PATH}" "${SCRIPT_DIR}/credentials.json"
  pip3 install -q google-auth-oauthlib google-api-python-client
  echo ""
  echo "브라우저가 열립니다. Google 계정으로 로그인 후 권한을 허용해주세요."
  echo ""
  TOKEN_JSON=$(python3 -c "
import json, sys
sys.path.insert(0, '.')
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file('credentials.json', ['https://www.googleapis.com/auth/gmail.readonly'])
creds = flow.run_local_server(port=0)
print(creds.to_json())
")
  gh secret set GMAIL_CREDENTIALS --body "${TOKEN_JSON}" --repo "${GITHUB_USER}/${REPO_NAME}"
  echo -e "${GREEN}   ✅ GMAIL_CREDENTIALS 등록됨${NC}"
  rm -f "${SCRIPT_DIR}/credentials.json"
fi

# ── 6. 초기 키워드 설정 ──────────────────────────────────────
echo ""
echo -e "${YELLOW}[6/6] 관심 키워드 설정${NC}"
echo "현재 기본값: large language model, retrieval augmented generation, multimodal learning"
echo -n "변경하시겠습니까? (y/N): "
read CHANGE_KW

if [ "${CHANGE_KW}" = "y" ] || [ "${CHANGE_KW}" = "Y" ]; then
  echo "쉼표로 구분해서 입력하세요. 예: reinforcement learning, RLHF, diffusion model"
  echo -n "키워드: "
  read KW_INPUT

  # state.json 업데이트
  python3 -c "
import json, sys
keywords = [k.strip() for k in '${KW_INPUT}'.split(',') if k.strip()]
with open('state.json') as f:
    state = json.load(f)
state['keywords'] = keywords
with open('state.json', 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
print(f'키워드 업데이트: {keywords}')
"
  git add state.json
  git diff --cached --quiet || git commit -m "chore: update initial keywords"
  git push
  echo -e "${GREEN}   ✅ 키워드 업데이트 완료${NC}"
fi

# ── 완료 ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   🎉 세팅 완료!                       ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "📍 레포: https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo ""
echo "⏰ 자동 실행 일정:"
echo "   • 매일 오전 9시 KST — 논문 다이제스트 발송"
echo "   • 4시간마다 — 이메일 회신 확인 및 키워드 업데이트"
echo ""
echo "🧪 지금 바로 테스트하려면:"
echo "   gh workflow run daily_digest.yml --repo ${GITHUB_USER}/${REPO_NAME}"
echo ""
echo "📊 실행 결과 확인:"
echo "   https://github.com/${GITHUB_USER}/${REPO_NAME}/actions"
echo ""
