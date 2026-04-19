# MAXAUTO

V-ARCHIVE 사이트에 플레이 기록을 자동으로 등록하는 프로그램입니다.  
본 프로젝트의 일부 코드 작성에는 AI가 활용되었습니다. :contentReference[oaicite:1]{index=1}

![Demo](Demo.png)

---

## 소개

MAXAUTO는 **DJMAX Respect V 플레이 후 결과 화면을 인식**하여  
V-ARCHIVE에 기록을 자동 등록하는 도구입니다.  
OCR 기반으로 동작하며, 모니터 해상도나 UI 배치에 따라 별도 설정이 필요할 수 있습니다. :contentReference[oaicite:2]{index=2}

---

## 설치

1. 우측 **Releases**에서 `MAXOCR.zip` 파일을 다운로드합니다. :contentReference[oaicite:3]{index=3}
2. 압축을 해제한 뒤, `MAXOCR.exe`가 `v-archive.exe` 또는 `account.txt`와 **같은 폴더**에 위치하도록 배치합니다. :contentReference[oaicite:4]{index=4}
3. 만약 `title.dat` 또는 `account.txt`가 없다면, 먼저 `v-archive.exe`를 **한 번 이상 실행**해 필요한 파일이 생성되도록 합니다. :contentReference[oaicite:5]{index=5}
4. 이후 `MAXOCR.exe`를 실행합니다. :contentReference[oaicite:6]{index=6}

---

## 초기 설정

### 1. 기본 해상도 확인

- 모니터 해상도가 **2560x1440**이라면 기본 설정으로도 동작할 수 있습니다.
- 다만 인식이 불안정할 수 있으므로, 필요 시 아래 설정 과정을 진행하는 것을 권장합니다. :contentReference[oaicite:7]{index=7}

### 2. 결과 화면 캡처 준비

정확한 OCR 인식을 위해 **결과 화면 스크린샷 1장**이 필요합니다.

1. 게임 결과 화면을 `Print Screen` 키로 캡처합니다.
2. 그림판 등 이미지 편집 프로그램에 붙여넣습니다.
3. `.png` 형식으로 저장합니다. :contentReference[oaicite:8]{index=8}

### 3. 박스 위치 조정

1. 프로그램 좌측 상단의 **이미지 열기** 버튼을 눌러 저장한 결과 화면 이미지를 불러옵니다. :contentReference[oaicite:9]{index=9}
2. 각 인식 박스를 실제 결과 화면 위치에 맞게 조정합니다. :contentReference[oaicite:10]{index=10}
3. 원하는 박스를 클릭한 뒤 **박스 재지정** 버튼으로 새로 지정하거나, 드래그해서 이동할 수 있습니다. :contentReference[oaicite:11]{index=11}
4. 가능한 한 **글자만 포함되도록** 박스를 좁게 잡으면 인식 오류를 줄일 수 있습니다. :contentReference[oaicite:12]{index=12}

<img alt="boxed" src="https://github.com/user-attachments/assets/8f21dc1a-86cc-4abb-996a-7df1f8aa268d"/>

### 4. 트리거 박스 설정

- **트리거 박스**는 특정 이미지와 거의 일치할 때만 인식을 시작하는 기준 영역입니다. :contentReference[oaicite:13]{index=13}
- 되도록 플레이 결과 화면에서 **항상 동일하게 표시되는 요소**를 지정하는 것을 권장합니다. :contentReference[oaicite:14]{index=14}
- 기본 제공 `OCR.json`에서는 `"F5"` 위치를 기준으로 설정되어 있습니다. :contentReference[oaicite:15]{index=15}

### 5. 설정 저장 및 템플릿 추출

1. 상단의 **설정 저장** 버튼을 눌러 `OCR.json` 파일로 저장합니다. :contentReference[oaicite:16]{index=16}
2. 상단의 **트리거 탬플릿 추출** 버튼을 눌러 트리거 박스 이미지를 저장합니다. :contentReference[oaicite:17]{index=17}

### 6. 실행

- **시작** 버튼을 누른 뒤 DJMAX Respect V를 플레이하면 됩니다. :contentReference[oaicite:18]{index=18}

---

## 사용 방법

1. 프로그램에 `OCR 로딩` 메시지가 표시되면 **시작 버튼**을 누릅니다.  
   최초 실행 시에는 OCR 엔진 다운로드로 인해 다소 시간이 걸릴 수 있습니다. :contentReference[oaicite:19]{index=19}

2. DJMAX Respect V 플레이 후 결과 화면에서, 오른쪽 상단에 박스가 표시될 때까지 기다립니다. :contentReference[oaicite:20]{index=20}

3. 박스가 표시되지 않는 경우 아래를 확인해 주세요.
   - 설정 과정을 올바르게 완료했는지
   - 시작 버튼을 눌렀는지 :contentReference[oaicite:21]{index=21}

4. 박스가 표시되는 동안 아래 키로 작업할 수 있습니다. :contentReference[oaicite:22]{index=22}

### 단축키

- `DEL` : 등록 작업 취소 :contentReference[oaicite:23]{index=23}
- `Insert` : 인식 오류 발생 시 재인식 :contentReference[oaicite:24]{index=24}
- `=` : 점수 등 수동 입력  
  - 아직 안정적이지 않은 기능이며, 프로그램 동작이 멈출 수 있습니다. :contentReference[oaicite:25]{index=25}

별도 입력이 없으면, 지정 시간(기본 **10초**) 후 자동으로 스코어를 등록합니다. :contentReference[oaicite:26]{index=26}

---

## 설정 항목 설명

### 트리거 박스
트리거 용도로 사용하는 박스를 지정합니다.  
특별한 이유가 없다면 변경하지 않는 것을 권장합니다. :contentReference[oaicite:27]{index=27}

### 템플릿 이미지
트리거 템플릿 이미지 경로입니다.  
위 가이드를 따라 설정했다면 변경하지 않는 것을 권장합니다. :contentReference[oaicite:28]{index=28}

### 저장 폴더
`스크린샷 저장`이 활성화되어 있을 경우, 인식 시마다 스크린샷과 텍스트 파일이 함께 저장되는 경로입니다.  
특별한 이유가 없다면 변경하지 않는 것을 권장합니다. :contentReference[oaicite:29]{index=29}

### 감시간격
트리거 박스의 인식 주기를 설정합니다.  
렉이 심한 경우 값을 조절해 보세요. :contentReference[oaicite:30]{index=30}

### 매칭기준
일반적으로 변경하지 않는 것을 권장합니다. :contentReference[oaicite:31]{index=31}

### 숫자박스
숫자로 인식해야 하는 항목들입니다.  
현재는 더 이상 사용하지 않으므로 변경하지 않는 것을 권장합니다. :contentReference[oaicite:32]{index=32}

### 점수반영 오버레이 시간
플레이 후 인식된 결과 오버레이를 화면에 표시하는 시간을 설정합니다.  
단위는 **초**입니다. :contentReference[oaicite:33]{index=33}

### 메세지 오버레이 시간
기타 메시지 오버레이를 표시하는 시간을 설정합니다.  
단위는 **초**입니다. :contentReference[oaicite:34]{index=34}

### 스크린샷 저장
활성화 시, 인식할 때마다 저장 폴더에 스크린샷을 저장합니다. :contentReference[oaicite:35]{index=35}

### 감지후 Enter까지 정지
감지 후 `Enter` 키를 입력해야 다음 인식을 진행합니다.  
`Enter` 입력 전까지는 다른 입력을 받지 않습니다. :contentReference[oaicite:36]{index=36}

> 곡 선택 화면으로 돌아가거나 곡 진입을 `Enter` 키로 했을 때  
> 자연스럽게 이어지도록 설계된 옵션입니다. :contentReference[oaicite:37]{index=37}

### 기록갱신 비교
로컬에 플레이 기록을 저장할지 여부를 선택합니다.  
특별한 이유가 없다면 변경하지 않는 것을 권장합니다. :contentReference[oaicite:38]{index=38}

---

## 문제 해결

### 박스가 표시되지 않아요
- 시작 버튼을 눌렀는지 확인해 주세요. :contentReference[oaicite:39]{index=39}
- OCR 설정 과정을 다시 진행해 주세요. :contentReference[oaicite:40]{index=40}
- 해상도 또는 UI 배치가 기본 설정과 다를 경우, 박스 위치를 재조정해 주세요. :contentReference[oaicite:41]{index=41}

### 인식이 자주 틀려요
- 박스를 글자만 포함하도록 더 좁게 잡아 보세요. :contentReference[oaicite:42]{index=42}
- 트리거 박스를 변하지 않는 UI 요소에 맞게 다시 설정해 보세요. :contentReference[oaicite:43]{index=43}
- `Insert` 키로 재인식을 시도해 보세요. :contentReference[oaicite:44]{index=44}

### 수동 입력(`=`) 사용 시 문제가 생겨요
- 현재 안정적이지 않은 기능이며, 프로그램 동작이 멈출 수 있습니다. :contentReference[oaicite:45]{index=45}

---

## 로드맵 / TODO

- 일정 확률로 `=` 키 입력 시 프로그램이 멈추는 문제 수정
- 로컬 DB 기준 기록 갱신 실패 시, `Enter`가 입력된 것으로 처리되는 버그 수정
- 갱신 성공 시 애니메이션 이벤트 추가
- 풀콤 / 퍼펙 전용 애니메이션 이벤트 추가
- 서버 DB를 로컬로 가져오는 기능 추가
- UI 개선
- 프로그램 이름을 **MAXAUTO**로 변경
- 오버레이 출력 순서를 키-난이도 순으로 변경
- 프로그램 자동 인식 기능 추가
- 하단 라이선스 문구 개선 :contentReference[oaicite:46]{index=46}

---

## 라이선스 및 고지

이 리포지토리 및 내부에 포함된 이미지는 제작자의 자산이 아니며,  
이미지에 대한 모든 저작권은 **DJMAX Respect V (Neowiz / ROCKY STUDIO)**에 있습니다. :contentReference[oaicite:47]{index=47}

본 프로그램 제작자는 **V-ARCHIVE와 관련이 없으며**,  
해당 사이트의 API 기능을 활용하여 제작되었습니다. :contentReference[oaicite:48]{index=48}

각 저작권자는 요청에 따라 삭제 또는 수정 요청을 할 수 있습니다. :contentReference[oaicite:49]{index=49}