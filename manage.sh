#!/bin/bash
# ============================================================
#  arXiv Digest 관리 스크립트
#  사용법: ./manage.sh [명령어]
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# git pull → stash pop 패턴으로 안전하게 푸시
safe_push() {
    local msg="$1"
    git stash
    git pull --rebase origin main
    git stash pop
    git add state.json
    git diff --cached --quiet || git commit -m "$msg"
    git push
    echo -e "${GREEN}✅ 완료${NC}"
}

show_help() {
    echo ""
    echo -e "${BLUE}arXiv Digest 관리 스크립트${NC}"
    echo ""
    echo "사용법: ./manage.sh [명령어]"
    echo ""
    echo "명령어:"
    echo "  status          현재 state.json 요약 출력"
    echo "  reset           피드백 state만 초기화 (sent_papers 유지)"
    echo "  reset-all       전체 초기화 (sent_papers 포함)"
    echo "  keywords        키워드 대화형 편집"
    echo "  seeds           시드 논문 대화형 편집"
    echo "  batch [N]       배치 크기 변경 (기본 4)"
    echo "  run             지금 바로 다이제스트 발송"
    echo "  logs            최근 실행 로그 확인"
    echo ""
}

cmd_status() {
    echo ""
    echo -e "${BLUE}=== 현재 State ===${NC}"
    python3 -c "
import json
with open('state.json') as f:
    s = json.load(f)

print(f'대기 중 (피드백):  {s.get(\"waiting_for_feedback\", False)}')
print(f'배치 크기:          {s.get(\"batch_size\", 4)}편')
print(f'발송된 논문 수:     {len(s.get(\"sent_papers\", []))}편')
print(f'피드백 이력:        {len(s.get(\"feedback_history\", []))}회')
print()
print('현재 키워드:')
for kw in s.get('keywords', []):
    print(f'  - {kw}')
print()
print(f'시드 논문: {len(s.get(\"seed_papers\", []))}편')
for sid in s.get('seed_papers', []):
    print(f'  - {sid}')
"
    echo ""
}

cmd_reset() {
    echo -e "${YELLOW}피드백 state를 초기화합니다 (sent_papers는 유지).${NC}"
    read -p "계속하시겠습니까? (y/N): " confirm
    [[ "$confirm" != "y" && "$confirm" != "Y" ]] && echo "취소" && exit 0

    python3 -c "
import json
with open('state.json') as f:
    s = json.load(f)
s['waiting_for_feedback'] = False
s['pending_feedback'] = []
s['processed_message_ids'] = []
with open('state.json', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print('초기화 완료 (발송된 논문 수:', len(s.get('sent_papers', [])), '편 유지)')
"
    safe_push "chore: reset feedback state"
}

cmd_reset_all() {
    echo -e "${RED}전체 state를 초기화합니다 (sent_papers 포함 — 모든 논문이 다시 발송됩니다).${NC}"
    read -p "정말 계속하시겠습니까? (y/N): " confirm
    [[ "$confirm" != "y" && "$confirm" != "Y" ]] && echo "취소" && exit 0

    python3 -c "
import json
with open('state.json') as f:
    s = json.load(f)
s['waiting_for_feedback'] = False
s['sent_papers'] = []
s['pending_feedback'] = []
s['processed_message_ids'] = []
s['feedback_history'] = []
with open('state.json', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print('전체 초기화 완료')
"
    safe_push "chore: reset all state"
}

cmd_keywords() {
    echo ""
    echo -e "${BLUE}현재 키워드:${NC}"
    python3 -c "
import json
with open('state.json') as f:
    s = json.load(f)
for i, kw in enumerate(s.get('keywords', []), 1):
    print(f'  {i}. {kw}')
"
    echo ""
    echo "새 키워드를 입력하세요 (쉼표로 구분)."
    echo "예: lifted inference, probabilistic logic, integrated gradients"
    echo -n "> "
    read kw_input

    python3 -c "
import json
keywords = [k.strip() for k in '''$kw_input'''.split(',') if k.strip()]
with open('state.json') as f:
    s = json.load(f)
s['keywords'] = keywords
with open('state.json', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print('키워드 업데이트:')
for kw in keywords:
    print(f'  - {kw}')
"
    safe_push "chore: update keywords"
}

cmd_seeds() {
    echo ""
    echo -e "${BLUE}현재 시드 논문:${NC}"
    python3 -c "
import json
with open('state.json') as f:
    s = json.load(f)
for i, sid in enumerate(s.get('seed_papers', []), 1):
    print(f'  {i}. {sid}')
"
    echo ""
    echo "1) 시드 논문 추가"
    echo "2) 시드 논문 전체 교체"
    echo -n "선택 (1/2): "
    read choice

    if [[ "$choice" == "1" ]]; then
        echo "추가할 arXiv ID를 쉼표로 구분해서 입력하세요."
        echo "예: 2211.01164, 1703.01365"
        echo -n "> "
        read new_ids
        python3 -c "
import json
new = [x.strip() for x in '''$new_ids'''.split(',') if x.strip()]
with open('state.json') as f:
    s = json.load(f)
existing = s.get('seed_papers', [])
added = [x for x in new if x not in existing]
s['seed_papers'] = existing + added
with open('state.json', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print(f'추가된 시드: {added}')
print(f'총 시드 논문: {len(s[\"seed_papers\"])}편')
"
    elif [[ "$choice" == "2" ]]; then
        echo "새 arXiv ID 목록을 쉼표로 구분해서 입력하세요."
        echo -n "> "
        read all_ids
        python3 -c "
import json
ids = [x.strip() for x in '''$all_ids'''.split(',') if x.strip()]
with open('state.json') as f:
    s = json.load(f)
s['seed_papers'] = ids
with open('state.json', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print(f'시드 논문 교체 완료: {len(ids)}편')
for sid in ids:
    print(f'  - {sid}')
"
    else
        echo "취소"
        exit 0
    fi

    safe_push "chore: update seed papers"
}

cmd_batch() {
    local n="${1:-4}"
    python3 -c "
import json
with open('state.json') as f:
    s = json.load(f)
s['batch_size'] = $n
with open('state.json', 'w') as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print(f'배치 크기 변경: {$n}편')
"
    safe_push "chore: set batch_size to $n"
}

cmd_run() {
    local REPO="$(gh api user --jq '.login')/arxiv-digest"
    echo -e "${YELLOW}다이제스트 발송 + 피드백 폴링을 시작합니다...${NC}"

    gh workflow run daily_digest.yml --repo "$REPO"
    echo -e "${GREEN}  ✅ 논문 발송 워크플로우 시작${NC}"

    gh workflow run process_feedback.yml --repo "$REPO"
    echo -e "${GREEN}  ✅ 피드백 폴링 워크플로우 시작${NC}"

    echo ""
    echo "30초 후 결과 확인:"
    echo "  ./manage.sh logs"
}

cmd_logs() {
    gh run list --repo "$(gh api user --jq '.login')/arxiv-digest" --limit 5
}

# ── 메인 ─────────────────────────────────────────────────────────────────

case "${1}" in
    status)     cmd_status ;;
    reset)      cmd_reset ;;
    reset-all)  cmd_reset_all ;;
    keywords)   cmd_keywords ;;
    seeds)      cmd_seeds ;;
    batch)      cmd_batch "${2}" ;;
    run)        cmd_run ;;
    logs)       cmd_logs ;;
    *)          show_help ;;
esac
