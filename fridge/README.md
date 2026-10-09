# 냉장고 셰프

냉장고 안이나 장 본 재료를 찍거나, 있는 재료를 적으면 오늘 해 먹을 메뉴를 골라 주고
**출처가 있는 레시피**를 찾아 정리해 주는 앱이에요.

- 웹: `https://yosebchoi.github.io/YoSebChoi/fridge/` (GitHub Pages가 `docs/`에서 배포될 때)
- Android 앱: https://github.com/YoSebChoi/YoSebChoi/releases/download/fridge-apk/fridge-chef.apk
  (폰에서 받고 "출처를 알 수 없는 앱" 설치 허용. 처음 한 번만 받으면 다음부터는 앱이 새 버전을 물어봐요)

## 쓰는 법

| 하고 싶은 것 | 방법 |
| --- | --- |
| 냉장고 사진으로 재료 담기 | 「사진 찍기」(여러 장 연속) 또는 「앨범에서 고르기」 → 「사진 속 재료 찾기」. 노란 재료는 짐작이니 아니면 빼요 |
| 직접 재료 담기 | 입력칸에 `계란, 양파, 김치`처럼 쉼표로 여러 개, 또는 아래 「+ 재료」 |
| 메뉴 추천 | 시간·종류·인분을 고르고 「오늘 뭐 해 먹을지 추천받기」 |
| 레시피 보기 | 메뉴를 누르면 레시피. 재료 옆 점: 초록 있어요, 빨강 필요해요, 회색 기본 양념 |
| 요리하면서 | 끝낸 단계를 누르면 줄이 그어져요. 레시피를 여는 동안 화면이 꺼지지 않아요 (끌 수 있음) |
| 저장·공유 | 레시피 위 책갈피 → 아래 「저장」 탭. 공유 버튼으로 카카오톡 등에 보내기 |

## 레시피를 믿을 수 있게

- **셰프의 추천**: Claude가 웹 검색으로 같은 요리의 레시피를 여러 곳에서 찾아 비교하고, 공통된 비율과 순서로 정리해요.
  공공기관(농촌진흥청 등), 식품회사 공식 레시피, 이름난 요리 연구가, 만개의레시피의 후기 많은 레시피를 먼저 봐요.
  레시피 아래 「출처」는 **실제 검색 결과에 있던 주소만** 보여 줘요 (AI가 지어낸 링크는 걸러요).
- **바로 만들 수 있는 집밥**: 인터넷이나 키 없이도 되는, 앱에 담긴 기본 가정식 레시피 30가지 (`fridge/recipes.js`).

## AI 설정 (Anthropic API 키)

사진 인식, 메뉴 추천, 출처 있는 레시피 찾기에는 각자의 Anthropic API 키가 필요해요.
앱의 ⚙ 설정에서 넣으면 그 폰에만 저장되고, Anthropic 말고는 어디에도 보내지 않아요.

1. https://console.anthropic.com 가입, 결제 수단 등록
2. API Keys → Create Key → 복사해서 앱 설정에 붙여 넣기

대략 비용 (Opus 기준, Sonnet은 절반쯤): 사진 인식 40원, 메뉴 추천 50원, 레시피 찾기 200~500원.
한 번 찾은 레시피는 저장돼서 다시 열어도 돈이 들지 않아요.

## 만들기

```sh
python3 fridge/build.py          # fridge/ → docs/fridge/ (버전, 서비스 워커, 매니페스트, 아이콘)
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
