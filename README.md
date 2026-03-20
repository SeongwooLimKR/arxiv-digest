# 📄 arXiv Digest

매일 arXiv 최신 논문을 자동으로 요약해서 이메일로 보내주는 시스템.
논문을 읽고 피드백을 회신하면 관심사에 맞게 키워드가 자동 업데이트됩니다.

## 설치

```bash
chmod +x setup.sh
./setup.sh
```

## 구조

```
arxiv-digest/
├── arxiv_digest.py          # 논문 수집·요약·발송
├── process_feedback.py      # 이메일 회신 파싱·키워드 업데이트
├── get_gmail_token.py       # Gmail OAuth 토큰 발급 (최초 1회)
├── state.json               # 키워드·발송 이력·피드백 상태
├── requirements.txt
└── .github/workflows/
    ├── daily_digest.yml     # 매일 09:00 KST 실행
    └── process_feedback.yml # 4시간마다 회신 확인
```

## 피드백 방법

이메일에 회신하면 됩니다.

**번호로 평가:**
```
1: 관심있음
2: 보통
3: 관심없음
```

**주제 변경:**
```
앞으로는 RLHF랑 alignment 관련 논문 위주로 보내줘
survey 논문은 빼줘
```

## 수동 실행

```bash
# 지금 바로 발송 테스트
gh workflow run daily_digest.yml

# 회신 처리 즉시 실행
gh workflow run process_feedback.yml
```
