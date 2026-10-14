# 네이버 블로그 시험관 후기 집계: 5일배 경과 14일 임테기 역전 → 심장소리 비율

순서 (각 단계 이어하기 가능, 요청 간 1~2초 딜레이·재시도 2회):

```bash
python collect.py --limit 300      # 1단계: data/candidates.csv (url, title, blogger=blogId, postdate, keyword)
python fetch_posts.py              # 본문 → .cache/posts (로컬 전용, 커밋 안 함)
python read_post.py <url>          # 2단계: 글 전체를 읽고 data/cases.csv에 직접 판정 기록
python cases.py                    # cases.csv 형식 검증 (스키마 설명은 cases.py 상단)
python followup.py                 # 3단계: 조건 충족 케이스의 같은 블로그 이후 글 후보 → data/followup_queue.csv
python summarize.py                # 4단계: results/summary.md
python -m unittest discover -s tests
```

- 네이버 API 키: `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` 환경변수가 있으면 헤더로 붙이고, 없으면 network secret 프록시가 붙인다고 가정.
- 판정은 키워드 매칭으로 하지 않는다. `read_post.py`는 날짜·일차 줄에 ▶ 표시만 한다.
- 개인정보: 블로그 URL(blogId 포함) 외에는 저장하지 않는다. 블로그 닉네임·본문 원문은 커밋하지 않는다.
- 경과일은 이식일 = 0 기준. "이식일 포함 15일차" = 경과 14일 = `test_d14`.
