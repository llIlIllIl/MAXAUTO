import json
import os
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None


class PaddleOCRGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PaddleOCR 이미지 OCR GUI")
        self.root.geometry("1400x900")

        self.ocr_engine = None
        self.ocr_ready = False
        self.current_image_path = None
        self.current_original_image = None
        self.current_result_image = None
        self.current_ocr_json = None

        self._build_ui()
        self._set_status("준비됨. 'OCR 엔진 초기화'를 눌러 시작하세요.")

    def _build_ui(self):
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(side=tk.TOP, fill=tk.X)

        self.init_button = ttk.Button(top_frame, text="OCR 엔진 초기화", command=self.init_ocr)
        self.init_button.pack(side=tk.LEFT, padx=5)

        self.open_button = ttk.Button(top_frame, text="이미지 열기", command=self.open_image, state=tk.DISABLED)
        self.open_button.pack(side=tk.LEFT, padx=5)

        self.run_button = ttk.Button(top_frame, text="OCR 실행", command=self.run_ocr, state=tk.DISABLED)
        self.run_button.pack(side=tk.LEFT, padx=5)

        self.save_text_button = ttk.Button(
            top_frame, text="텍스트 저장", command=self.save_text, state=tk.DISABLED
        )
        self.save_text_button.pack(side=tk.LEFT, padx=5)

        self.save_image_button = ttk.Button(
            top_frame, text="결과 이미지 저장", command=self.save_result_image, state=tk.DISABLED
        )
        self.save_image_button.pack(side=tk.LEFT, padx=5)

        self.confidence_label = ttk.Label(top_frame, text="최소 신뢰도:")
        self.confidence_label.pack(side=tk.LEFT, padx=(20, 5))

        self.confidence_var = tk.DoubleVar(value=0.5)
        self.confidence_spin = ttk.Spinbox(
            top_frame,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.confidence_var,
            width=8,
            format="%.2f",
        )
        self.confidence_spin.pack(side=tk.LEFT)

        self.lang_label = ttk.Label(top_frame, text="언어 힌트:")
        self.lang_label.pack(side=tk.LEFT, padx=(20, 5))

        self.lang_var = tk.StringVar(value="korean")
        self.lang_combo = ttk.Combobox(
            top_frame,
            textvariable=self.lang_var,
            values=["korean", "en", "ch", "japan"],
            width=10,
            state="readonly",
        )
        self.lang_combo.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w", padding=6)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        main_paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_frame = ttk.Frame(main_paned)
        right_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=3)
        main_paned.add(right_frame, weight=2)

        image_paned = ttk.Panedwindow(left_frame, orient=tk.VERTICAL)
        image_paned.pack(fill=tk.BOTH, expand=True)

        original_frame = ttk.LabelFrame(left_frame, text="원본 이미지", padding=5)
        result_frame = ttk.LabelFrame(left_frame, text="OCR 결과 이미지", padding=5)
        image_paned.add(original_frame, weight=1)
        image_paned.add(result_frame, weight=1)

        self.original_canvas = tk.Canvas(original_frame, bg="#222222")
        self.original_canvas.pack(fill=tk.BOTH, expand=True)

        self.result_canvas = tk.Canvas(result_frame, bg="#222222")
        self.result_canvas.pack(fill=tk.BOTH, expand=True)

        text_frame = ttk.LabelFrame(right_frame, text="OCR 텍스트 결과", padding=5)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text_widget = tk.Text(text_frame, wrap=tk.WORD, font=("Consolas", 11))
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.configure(yscrollcommand=scrollbar.set)

        self.original_canvas.bind("<Configure>", lambda event: self._refresh_canvases())
        self.result_canvas.bind("<Configure>", lambda event: self._refresh_canvases())

    def _set_status(self, text: str):
        self.status_var.set(text)
        self.root.update_idletasks()

    def init_ocr(self):
        if PaddleOCR is None:
            error_msg = (
                "paddleocr가 설치되어 있지 않습니다.\n"
                "다음 명령을 먼저 실행하세요:\n\n"
                "python -m pip install paddleocr pillow"
            )
            print("[ERROR] paddleocr import failed.", file=sys.stderr)
            print(error_msg, file=sys.stderr)
            messagebox.showerror("모듈 없음", error_msg)
            return

        self.init_button.config(state=tk.DISABLED)
        self._set_status("OCR 엔진 초기화 중... 최초 1회는 모델 다운로드로 시간이 걸릴 수 있습니다.")

        def worker():
            try:
                self.ocr_engine = PaddleOCR(
                    lang=self.lang_var.get(),
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
                self.ocr_ready = True
                self.root.after(0, self._on_ocr_initialized)
            except Exception as e:
                self.root.after(
                    0,
                    lambda e=e: self._on_error(e, "OCR 엔진 초기화 실패", reset_init=True),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_ocr_initialized(self):
        self._set_status("OCR 엔진 초기화 완료.")
        self.open_button.config(state=tk.NORMAL)
        self.init_button.config(state=tk.NORMAL)
        if self.current_image_path:
            self.run_button.config(state=tk.NORMAL)

    def open_image(self):
        file_path = filedialog.askopenfilename(
            title="이미지 선택",
            filetypes=[
                ("Image Files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.tif;*.tiff"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return

        try:
            image = Image.open(file_path).convert("RGB")
        except Exception as e:
            self._on_error(e, "이미지 열기 실패")
            return

        self.current_image_path = file_path
        self.current_original_image = image
        self.current_result_image = None
        self.current_ocr_json = None

        self.text_widget.delete("1.0", tk.END)
        self._refresh_canvases()

        if self.ocr_ready:
            self.run_button.config(state=tk.NORMAL)

        self.save_text_button.config(state=tk.DISABLED)
        self.save_image_button.config(state=tk.DISABLED)
        self._set_status(f"이미지 선택됨: {os.path.basename(file_path)}")

    def run_ocr(self):
        if not self.ocr_ready or self.ocr_engine is None:
            messagebox.showwarning("안내", "먼저 OCR 엔진을 초기화하세요.")
            return

        if not self.current_image_path:
            messagebox.showwarning("안내", "먼저 이미지를 선택하세요.")
            return

        self.run_button.config(state=tk.DISABLED)
        self._set_status("OCR 실행 중...")

        def worker():
            try:
                results = self.ocr_engine.predict(self.current_image_path)
                results = list(results)

                if not results:
                    raise RuntimeError("OCR 결과가 비어 있습니다.")

                res = results[0]

                result_json = getattr(res, "json", None)
                result_img_dict = getattr(res, "img", None)

                if result_json is None:
                    raise RuntimeError("OCR 결과에서 json 속성을 찾지 못했습니다.")

                vis_image = None
                if isinstance(result_img_dict, dict):
                    vis_image = result_img_dict.get("ocr_res_img") or result_img_dict.get("preprocessed_img")

                extracted_lines = self._extract_text_lines(result_json, self.confidence_var.get())
                text_output = "\n".join(extracted_lines).strip()

                if not text_output:
                    text_output = "(최소 신뢰도 조건에 맞는 텍스트가 없습니다.)"

                self.root.after(
                    0,
                    lambda: self._on_ocr_done(
                        result_json=result_json,
                        result_image=vis_image,
                        text_output=text_output,
                    ),
                )
            except Exception as e:
                self.root.after(
                    0,
                    lambda e=e: self._on_error(e, "OCR 실행 실패", reset_run=True),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _extract_text_lines(self, result_json: dict, min_conf: float):
        lines = []

        if not isinstance(result_json, dict):
            return lines

        data = result_json.get("res", result_json)

        rec_texts = data.get("rec_texts")
        rec_scores = data.get("rec_scores")

        if isinstance(rec_texts, list):
            if isinstance(rec_scores, list) and len(rec_scores) == len(rec_texts):
                for text, score in zip(rec_texts, rec_scores):
                    try:
                        score_value = float(score)
                    except Exception:
                        score_value = 0.0

                    if text and score_value >= min_conf:
                        lines.append(f"[{score_value:.3f}] {text}")
            else:
                for text in rec_texts:
                    if text:
                        lines.append(str(text))

        if lines:
            return lines

        collected = []
        self._walk_and_collect_text(data, collected, min_conf)
        return collected

    def _walk_and_collect_text(self, obj, collected, min_conf):
        if isinstance(obj, dict):
            if "rec_text" in obj:
                score = obj.get("rec_score", 1.0)
                try:
                    score_value = float(score)
                except Exception:
                    score_value = 0.0

                text = obj.get("rec_text")
                if text and score_value >= min_conf:
                    collected.append(f"[{score_value:.3f}] {text}")

            for key in ("text", "label", "content"):
                if key in obj and isinstance(obj[key], str):
                    value = obj[key].strip()
                    if value:
                        collected.append(value)

            for value in obj.values():
                self._walk_and_collect_text(value, collected, min_conf)

        elif isinstance(obj, list):
            for item in obj:
                self._walk_and_collect_text(item, collected, min_conf)

    def _on_ocr_done(self, result_json, result_image, text_output):
        self.current_ocr_json = result_json
        self.current_result_image = result_image if result_image is not None else self.current_original_image

        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert(tk.END, text_output)

        self._refresh_canvases()
        self.run_button.config(state=tk.NORMAL)
        self.save_text_button.config(state=tk.NORMAL)
        self.save_image_button.config(state=tk.NORMAL)
        self._set_status("OCR 완료.")

    def save_text(self):
        if not self.current_ocr_json:
            messagebox.showwarning("안내", "저장할 OCR 결과가 없습니다.")
            return

        file_path = filedialog.asksaveasfilename(
            title="텍스트 저장",
            defaultextension=".txt",
            filetypes=[("Text File", "*.txt"), ("JSON File", "*.json"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        try:
            if file_path.lower().endswith(".json"):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self.current_ocr_json, f, ensure_ascii=False, indent=2)
            else:
                text_data = self.text_widget.get("1.0", tk.END).strip()
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(text_data)
        except Exception as e:
            self._on_error(e, "파일 저장 실패")
            return

        self._set_status(f"저장 완료: {file_path}")

    def save_result_image(self):
        if self.current_result_image is None:
            messagebox.showwarning("안내", "저장할 결과 이미지가 없습니다.")
            return

        file_path = filedialog.asksaveasfilename(
            title="결과 이미지 저장",
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg;*.jpeg"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        try:
            self.current_result_image.save(file_path)
        except Exception as e:
            self._on_error(e, "이미지 저장 실패")
            return

        self._set_status(f"결과 이미지 저장 완료: {file_path}")

    def _refresh_canvases(self):
        self._draw_image_on_canvas(self.original_canvas, self.current_original_image)
        self._draw_image_on_canvas(self.result_canvas, self.current_result_image)

    def _draw_image_on_canvas(self, canvas: tk.Canvas, pil_image: Image.Image | None):
        canvas.delete("all")

        if pil_image is None:
            return

        canvas_width = max(canvas.winfo_width(), 1)
        canvas_height = max(canvas.winfo_height(), 1)
        img_width, img_height = pil_image.size

        scale = min(canvas_width / img_width, canvas_height / img_height)
        new_width = max(1, int(img_width * scale))
        new_height = max(1, int(img_height * scale))

        resized = pil_image.resize((new_width, new_height), Image.LANCZOS)
        tk_image = ImageTk.PhotoImage(resized)

        x = (canvas_width - new_width) // 2
        y = (canvas_height - new_height) // 2

        canvas.create_image(x, y, anchor=tk.NW, image=tk_image)
        canvas.image = tk_image

    def _on_error(self, exception: Exception, title: str = "오류", reset_init: bool = False, reset_run: bool = False):
        if reset_init:
            self.init_button.config(state=tk.NORMAL)
        if reset_run:
            self.run_button.config(state=tk.NORMAL)

        self._set_status("오류 발생")

        error_text = f"{title}:\n{exception}"

        print("\n" + "=" * 80, file=sys.stderr)
        print(f"[{title}]", file=sys.stderr)
        print(f"Type: {type(exception).__name__}", file=sys.stderr)
        print(f"Message: {exception}", file=sys.stderr)
        print("-" * 80, file=sys.stderr)

        if exception.__traceback__ is not None:
            traceback.print_exception(type(exception), exception, exception.__traceback__, file=sys.stderr)
        else:
            print("Traceback 정보를 찾을 수 없습니다.", file=sys.stderr)

        print("=" * 80 + "\n", file=sys.stderr)

        # 메시지박스에는 너무 긴 traceback 대신 핵심만 표시
        messagebox.showerror(title, error_text)


def main():
    root = tk.Tk()
    style = ttk.Style(root)

    try:
        style.theme_use("clam")
    except Exception:
        pass

    app = PaddleOCRGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
