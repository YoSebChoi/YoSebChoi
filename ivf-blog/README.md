# 네이버 블로그 시험관 후기 집계: 5일배 경과 14일 임테기 역전 → 심장소리 비율

순서 (각 단계 이어하기 가능, 요청 간 1~2초 딜레이·재시도 2회):

```bash
python collect.py --limit 300      # 1단계: data/candidates.csv (url, title, blogger=blogId, postdate, keyword)
python fetch_posts.py              # 본문 → .cache/posts (로컬 전용, 커밋 안 함)
python read_post.py <url>          # 2단계: 글 전체를 읽고 data/cases.csv에 직접 판정 기록
python cases.py                    # cases.csv 형식 검증 (스키마 설명은 cases.py 상단)
python collect.py --day4           # 4일배아 키워드로 후보 추가 수집
python collect.py --day3           # 3일배아 키워드로 후보 추가 수집(제목에 3일배아 표현 있는 글만)
python followup.py                 # 3단계: 조건 충족 케이스의 같은 블로그 이후 글 후보 → data/followup_queue.csv
python report.py                   # 결과 보고서 HTML → results/report.html
python followup_log.py build       # 읽은 결과를 data/followup_log.csv로 기록(케이스당 한 줄: 마지막 확인일·마지막 글 번호·판정 근거)
python followup_log.py status --unknown  # 원문을 다시 읽지 않고 기록만으로 검토
python followup_log.py recheck     # 미확인 케이스는 마지막으로 본 글 이후 새 글만 조회
python followup_log.py snip CASE   # 새로 생긴 후보 글만 결과 키워드 주변 짧게 출력
python summarize.py                # 4단계: results/summary.md
python -m unittest discover -s tests
```

- 검색 API 키 (`common.search_endpoint`):
  - NAVER API HUB(네이버 클라우드 플랫폼, 신규 발급은 여기서): `NCP_API_KEY_ID` / `NCP_API_KEY` → `naverapihub.apigw.ntruss.com`
  - 기존 개발자센터 키: `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` → `openapi.naver.com` (2027-06-30 지원 종료 예정)
  - 둘 다 없으면 network secret 프록시가 헤더를 붙인다고 가정. 엔드포인트가 바뀌면 `NAVER_SEARCH_URL`로 덮어쓰기.
- 판정은 키워드 매칭으로 하지 않는다. `read_post.py`는 날짜·일차 줄에 ▶ 표시만 한다.
- 개인정보: 블로그 URL(blogId 포함) 외에는 저장하지 않는다. 블로그 닉네임·본문 원문은 커밋하지 않는다.
- 경과일은 이식일 = 0 기준. "이식일 포함 15일차" = 경과 14일 = `test_d14`.

## 토큰 적게 쓰는 판정 순서 (review.py)

원문 전체를 읽지 않고 필요한 문장만 보고, 판정은 한 줄씩 남긴다. 다시 볼 때는 `cases.csv`(evidence·ambiguous)와 `followup_log.csv`만 보면 된다.

```
python review.py read 1686 2172 --day 4 --auto | python review.py add --day 4   # 역전 언급 없는 글 자동 제외
python review.py read 1686 2172 --day 4        # 남은 글: '역전' 주변·이식일·결과 문장만 발췌(이미 판정한 글은 건너뜀)
python review.py add --day 4 < 판정줄           # idx|신선/동결|이식일|basis|역전일|결과|쌍둥이|근거[|애매|후속URL] 또는 X|idx|사유
python followup.py --unknown                   # 미확인 케이스의 후속 글 후보(이미 기록된 케이스는 건너뜀)
python review.py titles --day 4                # 후속 글 제목만 한 줄로 — 대부분 제목으로 결과 판정
python review.py snip CASE_ID ...              # 제목으로 애매한 케이스만 결과 문장 발췌
python review.py outcome < 결과줄               # case_id|결과|주수|제목키워드|쌍둥이|메모
python report.py                   # 결과 보고서 HTML → results/report.html
python followup_log.py build                   # 케이스당 한 줄 기록 갱신
python birth.py collect                        # 심장소리 확인 케이스의 이후 글 제목으로 출산·유산 판정 → data/birth_log.csv
python birth.py review                         # 자동 판정 중 확인이 필요한 줄만(유산?·추적불가·예정일 지난 진행중)
python birth.py set < 판정줄                    # case_id|출산/유산/진행중/추적불가|마지막주수|메모 (다음 collect에서도 유지)
python birth_report.py                         # 출산 보고서 HTML → results/birth_report.html
python milestones.py collect                    # 아기집·난황·심장소리 첫 확인 주수 추출 → data/milestone_log.csv
python milestones.py review                     # 순서가 어긋나거나 범위 밖인 값만 근거 문장과 함께
python milestones.py set < 판정줄               # case_id|아기집|난황|심장|메모 (5w3d 형식, - 는 지움)
python milestone_report.py                     # 시기 보고서 HTML → results/milestone_report.html
python hcg.py collect                          # 피검 수치·측정일 추출(5일배 기준 경과일) → data/hcg_log.csv
python hcg.py review / set                     # 범위 밖·역행 값 확인, 수동 기록
python hcg_report.py --mine 9:90,14:1695       # 내 수치 위치·확률 보고서 → results/my_hcg_report.html (커밋 안 함)
```
