import os
import sys
import shutil
import urllib.request
import subprocess
from pathlib import Path

try:
    import pytesseract
    from PIL import Image
except ImportError:
    print("필수 패키지가 없습니다. 아래 명령으로 설치하세요:")
    print("pip install pytesseract pillow")
    sys.exit(1)


# =========================
# 설정값
# =========================
LANGUAGES = ["eng", "kor", "jpn"]          # 다운로드할 언어
TESSDATA_REPO = "best"              # "fast" | "best" | "standard"
IMAGE_PATH = "sample.png"           # OCR 테스트용 이미지 경로
RUN_OCR_TEST = True                 # 이미지가 있으면 OCR 실행
CUSTOM_TESSERACT_CMD = None         # 필요 시 Tesseract 실행 파일 경로 직접 지정
# 예: r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# =========================
# 내부 함수
# =========================
def get_repo_base_url(repo_name: str) -> str:
    repo_map = {
        "fast": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main",
        "best": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main",
        "standard": "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main",
    }
    if repo_name not in repo_map:
        raise ValueError("TESSDATA_REPO는 'fast', 'best', 'standard' 중 하나여야 합니다.")
    return repo_map[repo_name]


def find_tesseract() -> str | None:
    if CUSTOM_TESSERACT_CMD:
        if Path(CUSTOM_TESSERACT_CMD).exists():
            return CUSTOM_TESSERACT_CMD
        return None

    found = shutil.which("tesseract")
    return found


def ensure_tesseract_exists() -> str:
    tesseract_cmd = find_tesseract()
    if not tesseract_cmd:
        print("Tesseract OCR 실행 파일을 찾지 못했습니다.")
        print("먼저 Tesseract를 설치하고 PATH에 추가하세요.")
        print("또는 CUSTOM_TESSERACT_CMD에 직접 경로를 넣으세요.")
        sys.exit(1)
    return tesseract_cmd


def download_language_files(tessdata_dir: Path, languages: list[str], repo_name: str) -> None:
    base_url = get_repo_base_url(repo_name)
    tessdata_dir.mkdir(parents=True, exist_ok=True)

    for lang in languages:
        file_path = tessdata_dir / f"{lang}.traineddata"
        if file_path.exists():
            print(f"[SKIP] 이미 존재함: {file_path}")
            continue

        url = f"{base_url}/{lang}.traineddata"
        print(f"[DOWNLOAD] {url}")
        try:
            urllib.request.urlretrieve(url, file_path)
            print(f"[OK] 저장 완료: {file_path}")
        except Exception as e:
            print(f"[ERROR] 다운로드 실패: {lang}")
            print(e)
            sys.exit(1)


def set_tessdata_prefix(project_dir: Path) -> None:
    os.environ["TESSDATA_PREFIX"] = str(project_dir)
    print(f"[ENV] TESSDATA_PREFIX = {os.environ['TESSDATA_PREFIX']}")


def list_installed_languages(tesseract_cmd: str) -> str:
    try:
        result = subprocess.run(
            [tesseract_cmd, "--list-langs"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print("[ERROR] tesseract --list-langs 실행 실패")
        print(e.stderr)
        sys.exit(1)


def run_ocr_test(image_path: str, languages: list[str], tesseract_cmd: str) -> None:
    image_file = Path(image_path)
    if not image_file.exists():
        print(f"[INFO] OCR 테스트용 이미지가 없어 건너뜁니다: {image_file}")
        return

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        img = Image.open(image_file)
        lang_string = "+".join(languages)
        text = pytesseract.image_to_string(img, lang=lang_string)

        print("\n===== OCR RESULT =====")
        print(text)
        print("======================\n")
    except Exception as e:
        print("[ERROR] OCR 실행 실패")
        print(e)
        sys.exit(1)


# =========================
# 메인 실행
# =========================
def main():
    project_dir = Path.cwd()
    tessdata_dir = project_dir / "tessdata"

    print("[1] Tesseract 실행 파일 확인")
    tesseract_cmd = ensure_tesseract_exists()
    print(f"[OK] Tesseract: {tesseract_cmd}")

    print("\n[2] 언어 데이터 다운로드")
    download_language_files(tessdata_dir, LANGUAGES, TESSDATA_REPO)

    print("\n[3] 환경변수 설정")
    set_tessdata_prefix(project_dir)

    print("\n[4] pytesseract에 tesseract 경로 연결")
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    print(f"[OK] pytesseract.pytesseract.tesseract_cmd = {tesseract_cmd}")

    print("\n[5] 설치 언어 확인")
    langs_output = list_installed_languages(tesseract_cmd)
    print(langs_output)

    print("\n[6] 다운로드한 언어 파일 확인")
    for lang in LANGUAGES:
        file_path = tessdata_dir / f"{lang}.traineddata"
        print(f"{lang}: {'존재함' if file_path.exists() else '없음'} -> {file_path}")

    if RUN_OCR_TEST:
        print("\n[7] OCR 테스트")
        run_ocr_test(IMAGE_PATH, LANGUAGES, tesseract_cmd)

    print("\n완료되었습니다.")


if __name__ == "__main__":
    main()
