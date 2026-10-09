# 냉장고 셰프

냉장고에 있는 재료를 고르면 오늘 해 먹을 메뉴를 골라 주고
**식품의약품안전처 레시피 DB**에서 찾아 주는 앱이에요. 키 없이 그냥 돼요.

- 웹: `https://yosebchoi.github.io/YoSebChoi/fridge/` (GitHub Pages가 `docs/`에서 배포될 때)
- Android 앱: https://github.com/YoSebChoi/YoSebChoi/releases/download/fridge-apk/fridge-chef.apk
  (폰에서 받고 "출처를 알 수 없는 앱" 설치 허용. 처음 한 번만 받으면 다음부터는 앱이 새 버전을 물어봐요)

## 쓰는 법

| 탭 | 하는 일 |
| --- | --- |
| 냉장고 | 「냉장고 열어 재료 고르기」나 입력칸으로 재료 담기. 담은 날을 기억해서 4일이 넘은 재료는 노랗게, 7일이 넘으면 빨갛게 보이고 추천에서 먼저 써요. 재료를 누르면 넣은 날을 바꾸거나 뺄 수 있어요 |
| 추천 | 스타일(한식·중식·일식·양식·세계 요리)·시간·종류·인분·빼고 싶은 것(매운 음식, 해산물, 돼지고기…)을 고르면 바로 메뉴가 나와요. 맨 위 「이것만 있으면 돼요」에서 살 것을 장보기 목록에 담아요 |
| 찾기 | 요리 이름이나 재료로 1,400가지 레시피 검색 |
| 식단 | 레시피에서 「식단에 담기」로 요일별 이번 주 식단. 「식단에 필요한 재료 넣기」로 장보기 목록을 만들고, 산 것에 체크하면 냉장고에도 담겨요. 「보내기」로 장보기 목록 링크 공유 |
| 저장 | 「만들어 봤어요」로 찍은 도장과 칭호, 저장한 레시피 |

레시피 화면: 인분 −/+로 분량이 바뀌어요. 만드는 법에 시간이 있으면 「10분 타이머」 버튼이 생겨요 (Android 앱은 화면이 꺼져도 알림). 「링크 보내기」로 받은 사람이 링크를 열면 그 레시피가 바로 열려요. 끝낸 단계를 누르면 줄이 그어지고, 레시피를 여는 동안 화면이 꺼지지 않아요.
설정(⚙)에서 못 먹는 재료를 적어 두면 추천과 찾기에서 빠져요.

## 레시피는 어디서 오나요

- **식품의약품안전처 「조리식품의 레시피 DB」** (식품안전나라 Open API): 정부가 공개한 레시피 1,100여 가지.
  재료와 분량, 단계별 사진, 열량·나트륨·단백질이 있어요. 공공누리 제1유형이라 출처를 밝히고 써요.
  GitHub Actions **냉장고 셰프 레시피 DB**가 받아서 앱에 넣고, 매달 4일에 새로 받아요.
- **앱에 담긴 레시피 258가지** (`fridge/recipes.js`): 집밥부터 외식 메뉴까지. 한식 111 (갈비찜, 육개장, 감자탕, 냉면…), 중식 35 (짜장면, 마라탕, 꿔바로우…), 일식 39 (텐동, 스키야키, 라멘…), 양식 48 (봉골레, 라자냐, 햄버거…), 세계 요리 25 (팟타이, 쌀국수, 타코, 버터치킨 커리…).
- 식약처 레시피에는 스타일 구분이 없어서, 요리 이름과 재료(두반장, 가쓰오, 바질 등)로 한식·중식·일식·양식·세계 요리를 나눠요.
- 둘 다 앱 안에 들어 있어서 **키도 인터넷도 없이** 재료를 맞춰 봐요.

### 식품안전나라 인증키 넣기 (처음 한 번)

1. https://www.foodsafetykorea.go.kr 회원가입 → 위쪽 「공공데이터 활용」 → 「인증키 신청」 (바로 나와요)
2. 이 저장소 GitHub → Settings → Secrets and variables → Actions → New repository secret
3. Name: `FOODSAFETY_KEY`, Secret: 받은 인증키 → Add secret
4. Actions → **냉장고 셰프 레시피 DB** → Run workflow (그다음부터는 매달 알아서 받아요)

## AI 기능 (선택)

앱 ⚙ 설정에 Anthropic API 키를 넣은 사람에게만 더해지는 기능이에요. 안 넣어도 앱은 다 돼요.

- 사진으로 재료 찾기 (냉장고·장 본 재료 사진)
- AI 셰프의 메뉴 추천, 웹에서 출처를 비교한 레시피 찾기 (검색 결과에 있던 링크만 출처로 보여 줘요)
- 대략 비용 (Opus 기준, Sonnet은 절반쯤): 사진 40원, 추천 50원, 레시피 찾기 200~500원

## 만들기

```sh
FOODSAFETY_KEY=... python3 fridge/fetch_recipes.py   # 식약처 레시피 DB → fridge/data/foodsafety.json
python3 fridge/build.py          # fridge/ → docs/fridge/ (버전, 레시피 DB, 서비스 워커, 매니페스트, 아이콘)
node fridge/assets/render_icon.mjs   # 아이콘 그림(icon.svg)을 고쳤을 때 PNG 다시 만들기 (playwright 필요)
python3 fridge-app/make_icons.py     # Android 런처 아이콘과 시작 화면 (APK 빌드 때도 자동)
```

- 페이지: `fridge/index.html` (한 파일), 기본 레시피 `fridge/recipes.js`
- AI: 공식 SDK `@anthropic-ai/sdk` 0.127.0을 브라우저용으로 묶은 `fridge/vendor/anthropic-sdk.mjs`
  (`npm i @anthropic-ai/sdk@0.127.0 esbuild` 후 `export { default } from "@anthropic-ai/sdk"`를
  `esbuild --bundle --format=esm --minify --platform=browser`로 묶음)
- Android 앱 `fridge-app/`: 라이브 페이지를 띄우는 Capacitor 셸. 웹을 고치면 앱에도 바로 반영되니 APK는 `fridge-app/`을 바꿀 때만 새로 만들어요.
  - 앱에서만 되는 것: 아이콘에서 이어지는 시작 화면, 화면이 꺼져도 울리는 요리 타이머 알림, 공유 링크를 앱에서 열기(앱 설정 → 기본으로 열기 → 지원되는 링크 추가), 앱 안 카메라(연속 촬영, 플래시), 뒤로가기(카메라 → 창 → 레시피 → 냉장고 탭 → 백그라운드), 공유 시트, 진동, 요리 중 화면 켜 두기, 앱 안 업데이트
  - 빌드: GitHub Actions **냉장고 셰프 APK** (`main`에 올라가면 릴리스 `fridge-apk`에 올려요)
  - 서명: 노포 지도·시약선 노트와 같은 저장소 Secret `ANDROID_SIGNING`
