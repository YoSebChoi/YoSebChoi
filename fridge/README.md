# 냉장고 셰프

냉장고에 있는 재료를 고르면 오늘 해 먹을 메뉴를 골라 주고
**식품의약품안전처 레시피 DB**에서 찾아 주는 앱이에요. 키 없이 그냥 돼요.

- 웹: `https://yosebchoi.github.io/YoSebChoi/fridge/` (GitHub Pages가 `docs/`에서 배포될 때)
- Android 앱: https://github.com/YoSebChoi/YoSebChoi/releases/download/fridge-apk/fridge-chef.apk
  (폰에서 받고 "출처를 알 수 없는 앱" 설치 허용. 처음 한 번만 받으면 다음부터는 앱이 새 버전을 물어봐요)

## 쓰는 법

| 하고 싶은 것 | 방법 |
| --- | --- |
| 재료 고르기 | 「냉장고 열어 재료 고르기」에서 칸별로 눌러 담기, 또는 입력칸에 `계란, 양파, 김치`처럼 |
| 사진으로 재료 담기 (AI, 선택) | 설정에 키를 넣으면 「사진 찍기」·「앨범에서 고르기」 → 「사진 속 재료 찾기」 |
| 메뉴 추천 | 스타일(한식·중식·일식·양식)·시간·종류·인분을 고르고 「오늘 뭐 해 먹을지 추천받기」 |
| 부족한 재료 | 결과 맨 위 「이것만 있으면 돼요」: 무엇을 사면 어떤 메뉴가 되는지, 갖고 있는 재료로 대신할 수 있는지. 「장보기 목록 보내기」로 공유 |
| 레시피 보기 | 메뉴를 누르면 레시피. 재료 옆 점: 초록 있어요, 빨강 필요해요, 회색 기본 양념 |
| 요리하면서 | 끝낸 단계를 누르면 줄이 그어져요. 레시피를 여는 동안 화면이 꺼지지 않아요 (끌 수 있음) |
| 저장·공유 | 레시피 위 책갈피 → 아래 「저장」 탭. 공유 버튼으로 카카오톡 등에 보내기 |

## 레시피는 어디서 오나요

- **식품의약품안전처 「조리식품의 레시피 DB」** (식품안전나라 Open API): 정부가 공개한 레시피 1,100여 가지.
  재료와 분량, 단계별 사진, 열량·나트륨·단백질이 있어요. 공공누리 제1유형이라 출처를 밝히고 써요.
  GitHub Actions **냉장고 셰프 레시피 DB**가 받아서 앱에 넣고, 매달 4일에 새로 받아요.
- **기본 집밥 78가지** (`fridge/recipes.js`): 김치찌개, 마파두부, 규동, 까르보나라처럼 한식·중식·일식·양식 집밥.
- 식약처 레시피에는 스타일 구분이 없어서, 요리 이름과 재료(두반장, 가쓰오, 바질 등)로 한식·중식·일식·양식을 나눠요.
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
  - 앱에서만 되는 것: 아이콘에서 이어지는 시작 화면, 앱 안 카메라(연속 촬영, 플래시), 뒤로가기(카메라 → 창 → 레시피 → 저장 탭 → 백그라운드), 공유 시트, 진동, 요리 중 화면 켜 두기, 앱 안 업데이트
  - 빌드: GitHub Actions **냉장고 셰프 APK** (`main`에 올라가면 릴리스 `fridge-apk`에 올려요)
  - 서명: 노포 지도·시약선 노트와 같은 저장소 Secret `ANDROID_SIGNING`
