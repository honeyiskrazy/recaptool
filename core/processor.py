import os
import cv2
import easyocr
import numpy as np
import logging
from simple_lama_inpainting import SimpleLama
from PIL import Image

logger = logging.getLogger(__name__)


class Processor:
    _reader_instance = None
    _lama_instance = None
    _yolo_instance = None

    def __init__(self, max_height: int = 2500):
        import torch
        self.max_height = max_height

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if self.device == 'cuda':
            try:
                torch.zeros(1).to('cuda')
            except Exception as e:
                logger.warning(f"CUDA test failed: {e}. Falling back to CPU.")
                self.device = 'cpu'

        logger.info(f"Hardware Acceleration Device: {self.device.upper()}")

        if Processor._reader_instance is None:
            logger.info("Initializing EasyOCR reader...")
            Processor._reader_instance = easyocr.Reader(['en'], gpu=(self.device == 'cuda'))
        self.reader = Processor._reader_instance

        if Processor._lama_instance is None:
            logger.info("Initializing LaMa inpainting model...")
            original_jit_load = torch.jit.load
            def safe_jit_load(*args, **kwargs):
                if 'map_location' not in kwargs:
                    kwargs['map_location'] = self.device
                return original_jit_load(*args, **kwargs)
            torch.jit.load = safe_jit_load
            try:
                Processor._lama_instance = SimpleLama(device=self.device)
            finally:
                torch.jit.load = original_jit_load
        self.lama = Processor._lama_instance

        # _yolo_instance: None = not tried, False = failed/disabled, object = loaded
        if Processor._yolo_instance is None:
            try:
                logger.info("Initializing YOLOv8s character detection model...")
                os.environ["YOLO_AUTOUPDATE"] = "false"
                from ultralytics import YOLO
                Processor._yolo_instance = YOLO('yolov8s.pt')
                logger.info("YOLOv8s ready.")
            except Exception as e:
                logger.warning(f"YOLO init failed ({e}). Character-aware cuts disabled.")
                Processor._yolo_instance = False
        self.yolo = Processor._yolo_instance

    # ─────────────────────────────────────────────────────────────────────────
    # Content-aware whitespace crop
    # ─────────────────────────────────────────────────────────────────────────

    def _crop_to_content(self, img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        white_active = False
        black_active = False
        for edge in [gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]]:
            if np.median(edge) > 230:
                white_active = True
            if np.median(edge) < 20:
                black_active = True

        is_bg = np.zeros_like(gray, dtype=bool)
        if white_active:
            is_bg |= (gray > 230)
        if black_active:
            is_bg |= (gray < 15)

        if not white_active and not black_active:
            return img

        bg_per_row = np.sum(is_bg, axis=1)
        content_rows = np.where(bg_per_row < gray.shape[1] * 0.98)[0]
        if len(content_rows) == 0:
            return img

        top_y = max(0, content_rows[0] - 10)
        bottom_y = min(gray.shape[0], content_rows[-1] + 10)

        if (bottom_y - top_y) > 10:
            return img[top_y:bottom_y, :]
        return img

    # ─────────────────────────────────────────────────────────────────────────
    # YOLO-based character forbidden zones
    # ─────────────────────────────────────────────────────────────────────────

    def _get_character_forbidden_zones(self, giant_img: np.ndarray) -> set:
        """Return a set of Y rows where a detected character exists (including buffer).
        Cuts landing on these rows will be avoided."""
        if not self.yolo:
            return set()

        h, w = giant_img.shape[:2]

        MAX_YOLO_H = 4096
        if h > MAX_YOLO_H:
            scale = MAX_YOLO_H / h
            yolo_img = cv2.resize(giant_img, (max(1, int(w * scale)), MAX_YOLO_H))
        else:
            scale = 1.0
            yolo_img = giant_img

        try:
            results = self.yolo(yolo_img, classes=[0], verbose=False, conf=0.25)
        except Exception as e:
            logger.warning(f"YOLO inference error: {e}")
            return set()

        BUFFER = 50
        forbidden = set()
        for r in results:
            for box in r.boxes.xyxy.cpu().numpy():
                _, y1, _, y2 = box
                orig_y1 = int(y1 / scale)
                orig_y2 = int(y2 / scale)
                for y in range(max(0, orig_y1 - BUFFER), min(h, orig_y2 + BUFFER)):
                    forbidden.add(y)

        logger.info(f"YOLO: {len(results[0].boxes) if results else 0} characters detected, "
                    f"{len(forbidden)} rows protected.")
        return forbidden

    # ─────────────────────────────────────────────────────────────────────────
    # Panel extraction — batch entry point
    # ─────────────────────────────────────────────────────────────────────────

    def extract_panels(self, slice_paths: list[str]) -> list[np.ndarray]:
        BATCH_SIZE = 30
        all_panels = []

        for batch_start in range(0, len(slice_paths), BATCH_SIZE):
            batch_paths = slice_paths[batch_start:batch_start + BATCH_SIZE]

            imgs = []
            for path in batch_paths:
                img = cv2.imread(path)
                if img is not None:
                    imgs.append(img)
            if not imgs:
                continue

            target_width = imgs[0].shape[1]
            for i in range(len(imgs)):
                if imgs[i].shape[1] != target_width:
                    scale = target_width / imgs[i].shape[1]
                    new_h = int(imgs[i].shape[0] * scale)
                    imgs[i] = cv2.resize(imgs[i], (target_width, new_h))

            giant_img = np.vstack(imgs)
            del imgs

            batch_panels = self._extract_panels_from_image(giant_img)
            all_panels.extend(batch_panels)
            del giant_img

        if not all_panels:
            for path in slice_paths:
                img = cv2.imread(path)
                if img is not None:
                    all_panels.append(self._crop_to_content(img))
                    break

        return all_panels

    # ─────────────────────────────────────────────────────────────────────────
    # Panel extraction — gutter detection + YOLO-aware smart cut
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_panels_from_image(self, giant_img: np.ndarray) -> list[np.ndarray]:
        gray = cv2.cvtColor(giant_img, cv2.COLOR_BGR2GRAY)
        width = giant_img.shape[1]
        h = giant_img.shape[0]

        white_pixels = np.sum(gray > 240, axis=1)
        black_pixels = np.sum(gray < 15, axis=1)
        row_std = np.std(gray, axis=1)

        is_gutter = (
            (white_pixels > width * 0.98) |
            (black_pixels > width * 0.85) |
            (row_std < 2.0)
        )
        content_rows = ~is_gutter

        # Get YOLO forbidden zones (rows inside character bounding boxes)
        try:
            forbidden_rows = self._get_character_forbidden_zones(giant_img)
        except Exception as e:
            logger.warning(f"Forbidden zone detection failed: {e}")
            forbidden_rows = set()

        panels = []
        in_panel = False
        start_y = 0
        min_panel_height = 200
        min_gutter_height = 15
        gutter_count = 0

        soft_limit = int(self.max_height * 0.72)
        hard_limit = self.max_height
        absolute_max = self.max_height * 2   # Emergency ceiling — cut regardless of characters

        for y, is_content in enumerate(content_rows):
            if is_content:
                if not in_panel:
                    start_y = y
                    in_panel = True
                gutter_count = 0

                panel_h = y - start_y

                if in_panel and panel_h > soft_limit:
                    # Prefer a cut that is both low-complexity AND outside a character
                    if row_std[y] < 15.0 and y not in forbidden_rows:
                        cropped = self._crop_to_content(giant_img[start_y:y, :])
                        if cropped is not None and cropped.shape[0] > 0:
                            panels.append(cropped)
                        start_y = y

                    elif panel_h > hard_limit:
                        search_start = max(start_y + soft_limit, y - 800)
                        search_end = y

                        # Best cut: lowest std among rows NOT in forbidden zones
                        safe_candidates = [
                            (i, row_std[i])
                            for i in range(search_start, search_end)
                            if i not in forbidden_rows
                        ]

                        if safe_candidates:
                            best_y = min(safe_candidates, key=lambda x: x[1])[0]
                        elif panel_h > absolute_max:
                            # Absolute ceiling — must cut, pick least-bad row in the zone
                            logger.warning(f"Absolute max ({absolute_max}px) exceeded. "
                                           f"Forced cut at y={y} (through character).")
                            best_offset = int(np.argmin(row_std[search_start:search_end]))
                            best_y = search_start + best_offset
                        else:
                            # Hard limit hit but safe candidates exist further ahead —
                            # keep growing and let a gutter (or absolute_max) decide.
                            continue

                        cropped = self._crop_to_content(giant_img[start_y:best_y, :])
                        if cropped is not None and cropped.shape[0] > 0:
                            panels.append(cropped)
                        start_y = best_y
            else:
                if in_panel:
                    gutter_count += 1
                    if gutter_count >= min_gutter_height:
                        end_y = y - gutter_count
                        if (end_y - start_y) >= min_panel_height:
                            cropped = self._crop_to_content(giant_img[start_y:end_y, :])
                            if cropped is not None and cropped.shape[0] > 0:
                                panels.append(cropped)
                        in_panel = False

        if in_panel:
            cropped = self._crop_to_content(giant_img[start_y:, :])
            if cropped is not None and cropped.shape[0] > 0:
                panels.append(cropped)

        return panels

    # ─────────────────────────────────────────────────────────────────────────
    # Text mask builder — precise bubble detection (white + dark) + flood-fill
    # ─────────────────────────────────────────────────────────────────────────

    def _build_text_mask(self, img_bgr: np.ndarray, ocr_results: list) -> np.ndarray:
        """Build a precise mask covering only the text bounding boxes.
        Dilates the text boxes by a small amount to cover anti-aliasing but 
        avoids masking the entire speech bubble to prevent LaMa from creating 
        giant solid-color blobs."""
        h, w = img_bgr.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        if not ocr_results:
            return mask

        # Draw the text bounding boxes
        for bbox, text, prob in ocr_results:
            pts = np.array(bbox, dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)

        # Dilate by 7px to cover text shadows/anti-aliasing, but keep it tight
        # so we don't bleed outside the speech bubbles into the artwork.
        kernel = np.ones((7, 7), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)

        return mask

    # ─────────────────────────────────────────────────────────────────────────
    # (Legacy) Smart crop — kept but still disabled in process_image
    # ─────────────────────────────────────────────────────────────────────────

    def _calculate_smart_crop(self, image_np, text_boxes):
        h, w = image_np.shape[:2]
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        top_crop_y = 0
        bottom_crop_y = h

        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if cw * ch > 0.6 * (w * h):
                continue
            is_speech_bubble = False
            for bbox, _, _ in text_boxes:
                tx1 = min([pt[0] for pt in bbox])
                ty1 = min([pt[1] for pt in bbox])
                tx2 = max([pt[0] for pt in bbox])
                ty2 = max([pt[1] for pt in bbox])
                ix1 = max(x, tx1); iy1 = max(y, ty1)
                ix2 = min(x + cw, tx2); iy2 = min(y + ch, ty2)
                if ix1 < ix2 and iy1 < iy2:
                    inter_area = (ix2 - ix1) * (iy2 - iy1)
                    text_area = (tx2 - tx1) * (ty2 - ty1)
                    if inter_area > 0.5 * text_area:
                        is_speech_bubble = True
                        break
            if is_speech_bubble:
                if y < h * 0.35:
                    top_crop_y = max(top_crop_y, y + ch)
                elif (y + ch) > h * 0.65:
                    bottom_crop_y = min(bottom_crop_y, y)

        if (bottom_crop_y - top_crop_y) < 50:
            return 0, h
        return top_crop_y, bottom_crop_y

    # ─────────────────────────────────────────────────────────────────────────
    # Main processing entry point
    # ─────────────────────────────────────────────────────────────────────────

    def process_image(self, image_path: str, output_path: str,
                      manual_crop_rect: list[int] = None,
                      upscale: bool = False) -> dict:
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not read image at {image_path}")

        if manual_crop_rect is not None:
            mx1, my1, mx2, my2 = manual_crop_rect
            ih, iw = img.shape[:2]
            mx1 = max(0, min(iw, mx1)); mx2 = max(0, min(iw, mx2))
            my1 = max(0, min(ih, my1)); my2 = max(0, min(ih, my2))
            if mx1 >= mx2 or my1 >= my2:
                raise ValueError("Invalid crop boundaries: resulting image is empty.")
            img = img[my1:my2, mx1:mx2]

        # 1. OCR
        ocr_results = self.reader.readtext(img)
        extracted_text = [r[1] for r in ocr_results]

        # Calculate text area ratio for auto-flagging text-heavy panels
        total_text_area = 0
        for bbox, _, _ in ocr_results:
            tx1 = min(pt[0] for pt in bbox)
            ty1 = min(pt[1] for pt in bbox)
            tx2 = max(pt[0] for pt in bbox)
            ty2 = max(pt[1] for pt in bbox)
            total_text_area += max(0, (tx2 - tx1) * (ty2 - ty1))
        
        img_area = img.shape[0] * img.shape[1]
        text_ratio = total_text_area / img_area if img_area > 0 else 0
        is_text_heavy = text_ratio > 0.08  # Flag if text boxes take up > 8% of the panel

        # 2. Build precise text + bubble mask
        mask = self._build_text_mask(img, ocr_results)

        # --- AUTO EDGE-CROP LOGIC ---
        gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        grad_y = np.abs(grad_y)
        
        ih, iw = img.shape[:2]
        crop_top = 0
        crop_bottom = ih
        
        for t_bbox, _, _ in ocr_results:
            tx1 = int(max(0, min(pt[0] for pt in t_bbox)))
            ty1 = int(max(0, min(pt[1] for pt in t_bbox)))
            tx2 = int(min(iw, max(pt[0] for pt in t_bbox)))
            ty2 = int(min(ih, max(pt[1] for pt in t_bbox)))
            
            if tx2 <= tx1 or ty2 <= ty1: continue
            
            # TOP BUBBLE
            if ty1 < 100:
                bubble_bottom = ty2
                # Scan downwards to find the bubble's bottom edge
                for y in range(ty2, min(ty2 + 150, ih)):
                    if np.max(grad_y[y, tx1:tx2]) > 50:
                        bubble_bottom = y
                        break
                ptop = bubble_bottom + 6  # 6px padding to cleanly remove bubble stroke
                if ptop < ih * 0.35 and ptop > crop_top:
                    crop_top = ptop
                    
            # BOTTOM BUBBLE
            if ty2 > ih - 100:
                bubble_top = ty1
                # Scan upwards to find the bubble's top edge
                for y in range(ty1, max(ty1 - 150, 0), -1):
                    if np.max(grad_y[y, tx1:tx2]) > 50:
                        bubble_top = y
                        break
                pbot = bubble_top - 6
                if pbot > ih * 0.65 and pbot < crop_bottom:
                    crop_bottom = pbot

        if crop_bottom - crop_top >= 0.65 * ih:
            if crop_top > 0 or crop_bottom < ih:
                img = img[crop_top:crop_bottom, 0:iw]
                mask = mask[crop_top:crop_bottom, 0:iw]

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 3. LaMa inpainting
        if np.count_nonzero(mask) > 0:
            img_pil = Image.fromarray(img_rgb)
            mask_pil = Image.fromarray(mask).convert('L')

            try:
                cleaned_pil = self.lama(img_pil, mask_pil)
            except RuntimeError as e:
                if 'out of memory' in str(e).lower():
                    import torch
                    torch.cuda.empty_cache()
                    orig_size = img_pil.size
                    for divisor in [2, 4]:
                        try:
                            s_img = img_pil.resize((orig_size[0] // divisor, orig_size[1] // divisor), Image.LANCZOS)
                            s_msk = mask_pil.resize((orig_size[0] // divisor, orig_size[1] // divisor), Image.NEAREST)
                            cleaned_pil = self.lama(s_img, s_msk)
                            cleaned_pil = cleaned_pil.resize(orig_size, Image.LANCZOS)
                            break
                        except RuntimeError:
                            torch.cuda.empty_cache()
                            if divisor == 4:
                                logger.error("Extreme OOM — skipping inpainting for this panel.")
                                cleaned_pil = img_pil
                else:
                    raise e

            cleaned_bgr = cv2.cvtColor(np.array(cleaned_pil), cv2.COLOR_RGB2BGR)
            
            if cleaned_bgr.shape[:2] != img.shape[:2]:
                cleaned_bgr = cv2.resize(cleaned_bgr, (img.shape[1], img.shape[0]))

            # 4. Feathered edge blend: smooths the LaMa boundary back into original artwork
            mask_blur = cv2.GaussianBlur(mask, (7, 7), 0)
            alpha = mask_blur.astype(np.float32) / 255.0
            alpha = alpha[:, :, np.newaxis]
            blended = img.astype(np.float32) * (1.0 - alpha) + cleaned_bgr.astype(np.float32) * alpha
            cleaned_img = blended.astype(np.uint8)
        else:
            cleaned_img = img

        crop_dims = [cleaned_img.shape[1], cleaned_img.shape[0]]

        # 5. Optional 2× upscale + unsharp mask
        if upscale:
            uh, uw = cleaned_img.shape[:2]
            up = cv2.resize(cleaned_img, (uw * 2, uh * 2), interpolation=cv2.INTER_LANCZOS4)
            gaussian = cv2.GaussianBlur(up, (0, 0), 2.0)
            final_img = cv2.addWeighted(up, 1.5, gaussian, -0.5, 0)
        else:
            final_img = cleaned_img

        cv2.imwrite(output_path, final_img)
        crop_dims = [final_img.shape[1], final_img.shape[0]]

        return {
            "ocr_text": extracted_text,
            "crop_dimensions": crop_dims,
            "suggested_for_deletion": bool((crop_dims[1] < 200) or is_text_heavy),
            "deleted": False
        }

    def apply_manual_crop(self, original_path: str, output_path: str, crop_rect: list[int]):
        return self.process_image(original_path, output_path, manual_crop_rect=crop_rect)
