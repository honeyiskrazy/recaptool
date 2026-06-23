import customtkinter as ctk
from PIL import Image
import os
from core.project_session import ProjectSession
from core.exporter import Exporter
from ui.crop_window import CropWindow
from concurrent.futures import ThreadPoolExecutor

# Create a global thread pool for loading thumbnails so we don't spawn 100 threads at once
_thumb_loader_pool = ThreadPoolExecutor(max_workers=4)

class SceneCard(ctk.CTkFrame):
    def __init__(self, master, scene_data, index, callbacks):
        super().__init__(master, fg_color=("gray80", "gray20"))
        self.scene_data = scene_data
        self.index = index
        self.callbacks = callbacks
        
        self.grid_columnconfigure(0, weight=0) # Image
        self.grid_columnconfigure(1, weight=1) # Info
        
        # Cleaned Image - larger size
        self.clean_img_label = ctk.CTkLabel(self, text="Loading...", width=400, height=550)
        self.clean_img_label.grid(row=0, column=0, padx=20, pady=20, sticky="n")
        
        def load_thumb():
            try:
                clean_path = scene_data.get("cleaned_image_path")
                if clean_path and os.path.exists(clean_path):
                    with Image.open(clean_path) as clean_img:
                        clean_img.thumbnail((400, 550))
                        img_copy = clean_img.copy()
                    
                    # MUST create CTkImage and update label on the main thread!
                    def _safe_update(img=img_copy):
                        try:
                            if self.clean_img_label.winfo_exists():
                                photo = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                                self.clean_img_label.configure(image=photo, text="")
                                self.clean_img_label.image = photo
                        except Exception as e:
                            print(f"Error in safe_update: {e}")
                    self.after(0, _safe_update)
            except Exception as e:
                print(f"Error in load_thumb: {e}")
                
        # Submit to thread pool instead of spawning a new raw thread
        _thumb_loader_pool.submit(load_thumb)
        
        # Column 1: Info & Controls
        self.info_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.info_frame.grid(row=0, column=1, sticky="nw", padx=20, pady=20)
            
        # Metadata
        self.id_label = ctk.CTkLabel(self.info_frame, text=f"Scene ID: {scene_data.get('scene_id')}", font=ctk.CTkFont(weight="bold", size=18))
        self.id_label.pack(anchor="w", pady=(0, 5))
        
        self.status_label = ctk.CTkLabel(self.info_frame, text="", font=ctk.CTkFont(size=14))
        self.status_label.pack(anchor="w", pady=(0, 20))
        
        # Controls in a 2x2 Grid
        self.btn_frame = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        self.btn_frame.pack(anchor="w")
        
        self.btn_font = ctk.CTkFont(size=14, weight="bold")
        self.del_btn = ctk.CTkButton(self.btn_frame, text="", width=140, height=40, font=self.btn_font, command=lambda: callbacks["toggle_flag"](index))
        self.del_btn.grid(row=0, column=0, padx=(0, 10), pady=10)
        
        self.crop_btn = ctk.CTkButton(self.btn_frame, text="Replace Crop", width=140, height=40, font=self.btn_font, command=lambda: callbacks["replace_crop"](index))
        self.crop_btn.grid(row=0, column=1, padx=10, pady=10)
        
        self.up_btn = ctk.CTkButton(self.btn_frame, text="Move Up", width=140, height=40, font=self.btn_font, command=lambda: callbacks["move_up"](index))
        self.up_btn.grid(row=1, column=0, padx=(0, 10), pady=10)
        
        self.down_btn = ctk.CTkButton(self.btn_frame, text="Move Down", width=140, height=40, font=self.btn_font, command=lambda: callbacks["move_down"](index))
        self.down_btn.grid(row=1, column=1, padx=10, pady=10)
        
        self.merge_btn = ctk.CTkButton(self.btn_frame, text="Merge ⬇️", width=290, height=40, font=self.btn_font, fg_color="#8b008b", hover_color="#551a8b", command=lambda: callbacks["merge_panels"](index))
        self.merge_btn.grid(row=2, column=0, columnspan=2, padx=(0, 0), pady=10)

        self.reinpaint_btn = ctk.CTkButton(self.btn_frame, text="🔄 Re-Inpaint", width=290, height=40, font=self.btn_font, fg_color="#1a5276", hover_color="#0e2f44", command=lambda: callbacks["reinpaint"](index))
        self.reinpaint_btn.grid(row=3, column=0, columnspan=2, padx=(0, 0), pady=(0, 10))
        
        self.update_ui()
        
    def update_ui(self):
        flags = []
        if self.scene_data.get("deleted"):
            flags.append("DELETED")
            self.configure(fg_color=("red", "darkred"))
            self.del_btn.configure(text="Restore", fg_color=["#3B8ED0", "#1F6AA5"], hover_color=["#36719F", "#144870"])
        else:
            if self.scene_data.get("suggested_for_deletion"):
                flags.append("FLAGGED")
                self.configure(fg_color=("orange", "darkorange"))
                self.del_btn.configure(text="Unflag", fg_color=["#3B8ED0", "#1F6AA5"], hover_color=["#36719F", "#144870"])
            else:
                self.configure(fg_color=("gray80", "gray20"))
                self.del_btn.configure(text="Flag", fg_color="orange", hover_color="darkorange")
                
        if self.scene_data.get("user_modified"):
            flags.append("MODIFIED")
            
        status_text = "Status: " + ", ".join(flags) if flags else "Status: Active"
        self.status_label.configure(text=status_text)


class ReviewView(ctk.CTkFrame):
    def __init__(self, master, session: ProjectSession, on_back_callback):
        super().__init__(master)
        self.session = session
        self.on_back_callback = on_back_callback
        
        self.grid_columnconfigure(0, weight=1)
        
        # Pagination variables
        self.current_page = 0
        self.items_per_page = 50
        
        # --- Stats Frame ---
        self.stats_frame = ctk.CTkFrame(self, height=30, fg_color="transparent")
        self.stats_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(5, 0))
        
        self.stats_label = ctk.CTkLabel(self.stats_frame, text="CPU: 0% | RAM: 0% | GPU: N/A | Total Images: 0 | Total Flagged: 0", font=ctk.CTkFont(size=12, weight="bold"))
        self.stats_label.pack(side="right")
        
        # --- Toolbar ---
        self.toolbar = ctk.CTkFrame(self)
        self.toolbar.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        
        ctk.CTkLabel(self.toolbar, text="Manual Review Stage", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=10)
        
        self.home_btn = ctk.CTkButton(self.toolbar, text="Back to Home", fg_color="gray", hover_color="darkgray", command=self.on_back_callback)
        self.home_btn.pack(side="left", padx=10, pady=10)
        
        self.next_btn = ctk.CTkButton(self.toolbar, text="Save & Next Episode  [Combined Ep Draft]", fg_color="#b8860b", hover_color="#8b6508", command=self.load_next_episode)
        self.next_btn.pack(side="left", padx=10, pady=10)
        
        self.export_btn = ctk.CTkButton(self.toolbar, text="Generate CapCut Package  [Single Ep Draft]", fg_color="green", hover_color="darkgreen", command=self.show_export_validation)
        self.export_btn.pack(side="right", padx=10, pady=10)
        
        self.bulk_del_btn = ctk.CTkButton(self.toolbar, text="Delete All Flagged", fg_color="red", hover_color="darkred", command=self.delete_flagged)
        self.bulk_del_btn.pack(side="right", padx=10, pady=10)
        
        # --- Animation Settings ---
        self.anim_frame = ctk.CTkFrame(self)
        self.anim_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        
        self.apply_motion_var = ctk.BooleanVar(value=False)
        self.apply_motion_cb = ctk.CTkCheckBox(self.anim_frame, text="Apply Motion Presets", variable=self.apply_motion_var, command=self.toggle_motion_cbs, font=ctk.CTkFont(weight="bold"))
        self.apply_motion_cb.pack(side="left", padx=(10, 20), pady=10)
        
        ctk.CTkLabel(self.anim_frame, text="Allowed Animations:").pack(side="left", padx=10, pady=5)
        
        self.anim_vars = {}
        self.anim_checkboxes = []
        for anim in ["Zoom In", "Zoom Out", "Pan Left", "Pan Right", "Pan Up", "Pan Down"]:
            var = ctk.BooleanVar(value=False)
            self.anim_vars[anim] = var
            cb = ctk.CTkCheckBox(self.anim_frame, text=anim, variable=var, width=80)
            cb.pack(side="left", padx=5, pady=5)
            self.anim_checkboxes.append(cb)
            
        self.toggle_motion_cbs()
        
        # --- Pagination Frame ---
        self.pagination_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.pagination_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        
        self.prev_page_btn = ctk.CTkButton(self.pagination_frame, text="< Previous Page", width=120, command=self.prev_page)
        self.prev_page_btn.pack(side="left", padx=10)
        
        self.page_label = ctk.CTkLabel(self.pagination_frame, text="Page 1 / 1", font=ctk.CTkFont(weight="bold"))
        self.page_label.pack(side="left", expand=True)
        
        self.next_page_btn = ctk.CTkButton(self.pagination_frame, text="Next Page >", width=120, command=self.next_page)
        self.next_page_btn.pack(side="right", padx=10)
        
        # --- Scrollable List ---
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=(5, 10))
        self.grid_rowconfigure(4, weight=1)
        
        self.refresh_list()
        self.update_stats_loop()

    def update_stats_loop(self):
        try:
            # Guard: stop loop if widget is destroyed
            if not self.winfo_exists():
                return
                
            import psutil
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            
            gpu_text = "N/A"
            try:
                import GPUtil
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    gpu_text = f"{gpu.load * 100:.1f}% ({gpu.memoryUsed:.0f}MB)"
            except Exception:
                pass
                
            scenes = self.session.get_all_scenes()
            total = len(scenes)
            flagged = sum(1 for s in scenes if s.get("suggested_for_deletion") or s.get("deleted"))
            
            text = f"\u2699\ufe0f CPU: {cpu}% | RAM: {ram}% | GPU: {gpu_text} | \U0001f5bc\ufe0f Loaded: {total} | \U0001f5d1\ufe0f Flagged: {flagged}"
            self.stats_label.configure(text=text)
        except Exception:
            pass
            
        # Only reschedule if widget still alive
        try:
            if self.winfo_exists():
                self.after(2000, self.update_stats_loop)
        except Exception:
            pass

    def toggle_motion_cbs(self):
        is_applied = self.apply_motion_var.get()
        state = "normal" if is_applied else "disabled"
        for cb in self.anim_checkboxes:
            cb.configure(state=state)
            
        if is_applied:
            for var in self.anim_vars.values():
                var.set(True)
        else:
            for var in self.anim_vars.values():
                var.set(False)

    def refresh_list(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
            
        callbacks = {
            "toggle_flag": self.toggle_flag,
            "move_up": self.move_up,
            "move_down": self.move_down,
            "replace_crop": self.replace_crop,
            "merge_panels": self.merge_panels,
            "save_script": self.save_script,
            "reinpaint": self.reinpaint
        }
        
        scenes = self.session.get_all_scenes()
        total_scenes = len(scenes)
        
        import math
        total_pages = max(1, math.ceil(total_scenes / self.items_per_page))
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)
            
        self.page_label.configure(text=f"Page {self.current_page + 1} / {total_pages}")
        self.prev_page_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_page_btn.configure(state="normal" if self.current_page < total_pages - 1 else "disabled")
        
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, total_scenes)
        
        scenes_to_show = scenes[start_idx:end_idx]
        
        # FIX: Tkinter Canvas has a maximum height limit of 32,767 pixels on Windows.
        # Solution: Use a multi-column grid AND pagination to keep total height under the limit safely.
        num_columns = 2
        
        for i, scene in enumerate(scenes_to_show):
            actual_idx = start_idx + i
            card = SceneCard(self.scroll_frame, scene, actual_idx, callbacks)
            row = i // num_columns
            col = i % num_columns
            card.grid(row=row, column=col, sticky="nsew", padx=10, pady=10)
            
        # Ensure columns have equal weight
        for c in range(num_columns):
            self.scroll_frame.grid_columnconfigure(c, weight=1)
            
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_list()
            
    def next_page(self):
        import math
        scenes = self.session.get_all_scenes()
        total_pages = max(1, math.ceil(len(scenes) / self.items_per_page))
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.refresh_list()
            
    def save_script(self, index, new_text_list):
        self.session.update_scene(index, {"ocr_text": new_text_list})
        
    def toggle_flag(self, index):
        scene = self.session.get_all_scenes()[index]
        if scene.get("deleted", False):
            self.session.update_scene(index, {"deleted": False, "suggested_for_deletion": False})
        else:
            new_status = not scene.get("suggested_for_deletion", False)
            self.session.update_scene(index, {"suggested_for_deletion": new_status})

        for widget in self.scroll_frame.winfo_children():
            if isinstance(widget, SceneCard) and widget.index == index:
                widget.scene_data = self.session.get_all_scenes()[index]
                widget.update_ui()
                break
        
    def move_up(self, index):
        if index > 0:
            self.session.swap_scenes(index, index - 1)
            self.refresh_list()
            
    def move_down(self, index):
        scenes = self.session.get_all_scenes()
        if index < len(scenes) - 1:
            self.session.swap_scenes(index, index + 1)
            self.refresh_list()
            
    def delete_flagged(self):
        scenes = self.session.get_all_scenes()
        changed = False
        for i, scene in enumerate(scenes):
            if scene.get("suggested_for_deletion") and not scene.get("deleted"):
                scenes[i]["deleted"] = True
        changed = True
        if changed:
            self.session.save()
        self.refresh_list()
        
    def merge_panels(self, index):
        import cv2
        import numpy as np
        import os
        
        scenes = self.session.get_all_scenes()
        if index >= len(scenes) - 1:
            print("Cannot merge the last panel.")
            return
            
        current_scene = scenes[index]
        next_scene = scenes[index + 1]
        
        img1_path = current_scene.get("cleaned_image_path")
        img2_path = next_scene.get("cleaned_image_path")
        
        if not img1_path or not img2_path or not os.path.exists(img1_path) or not os.path.exists(img2_path):
            print("Missing cleaned image paths.")
            return
            
        try:
            # 1. Merge cleaned images
            img1 = cv2.imread(img1_path)
            img2 = cv2.imread(img2_path)
            
            if img1 is not None and img2 is not None:
                if img1.shape[1] != img2.shape[1]:
                    img2 = cv2.resize(img2, (img1.shape[1], img2.shape[0]))
                merged_img = np.vstack((img1, img2))
                cv2.imwrite(img1_path, merged_img)
                
            # 2. Merge raw images
            raw1_path = current_scene.get("image_path")
            raw2_path = next_scene.get("image_path")
            
            if raw1_path and raw2_path and os.path.exists(raw1_path) and os.path.exists(raw2_path):
                raw1 = cv2.imread(raw1_path)
                raw2 = cv2.imread(raw2_path)
                if raw1 is not None and raw2 is not None:
                    if raw1.shape[1] != raw2.shape[1]:
                        raw2 = cv2.resize(raw2, (raw1.shape[1], raw2.shape[0]))
                    merged_raw = np.vstack((raw1, raw2))
                    cv2.imwrite(raw1_path, merged_raw)
                    
            # 3. Combine scripts if they exist
            script1 = current_scene.get("script", "")
            script2 = next_scene.get("script", "")
            combined_script = f"{script1}\n{script2}".strip()
            if combined_script:
                current_scene["script"] = combined_script
                
            # 4. Remove next scene and save
            scenes.pop(index + 1)
            self.session.save()
            
            # Refresh UI
            self.refresh_list()
        except Exception as e:
            print(f"Error merging panels: {e}")
            
    def reinpaint(self, index):
        """Re-run OCR + LaMa inpainting on the original raw image for the given panel."""
        import threading
        scenes = self.session.get_all_scenes()
        if index >= len(scenes):
            return

        scene = scenes[index]
        orig_path = scene.get("original_image_path") or scene.get("image_path")
        clean_path = scene.get("cleaned_image_path")

        if not orig_path or not os.path.exists(orig_path):
            from tkinter import messagebox
            messagebox.showerror("Re-Inpaint", "Original image not found for this panel.")
            return
        if not clean_path:
            from tkinter import messagebox
            messagebox.showerror("Re-Inpaint", "No cleaned image path stored for this panel.")
            return

        # Find the card widget and disable its button while processing
        target_card = None
        for widget in self.scroll_frame.winfo_children():
            if isinstance(widget, SceneCard) and widget.index == index:
                target_card = widget
                break

        if target_card:
            target_card.reinpaint_btn.configure(state="disabled", text="Processing...")

        def _run():
            try:
                from core.processor import Processor
                p = Processor()
                
                # Fetch upscale setting from the main app
                upscale_setting = False
                if hasattr(self.winfo_toplevel(), "current_upscale"):
                    upscale_setting = self.winfo_toplevel().current_upscale
                    
                p.process_image(
                    orig_path, 
                    clean_path,
                    manual_crop_rect=scene.get("manual_crop"),
                    upscale=upscale_setting
                )

                def _done():
                    if target_card and target_card.winfo_exists():
                        target_card.reinpaint_btn.configure(state="normal", text="🔄 Re-Inpaint")
                        # Reload thumbnail
                        try:
                            with Image.open(clean_path) as img:
                                img.thumbnail((400, 550))
                                img_copy = img.copy()
                            photo = ctk.CTkImage(light_image=img_copy, dark_image=img_copy, size=img_copy.size)
                            target_card.clean_img_label.configure(image=photo, text="")
                            target_card.clean_img_label.image = photo
                        except Exception as e:
                            print(f"Thumbnail reload error: {e}")
                    self.session.update_scene(index, {"user_modified": True})
                self.after(0, _done)
            except Exception as e:
                def _err(err=str(e)):
                    if target_card and target_card.winfo_exists():
                        target_card.reinpaint_btn.configure(state="normal", text="🔄 Re-Inpaint")
                    from tkinter import messagebox
                    messagebox.showerror("Re-Inpaint Failed", f"Error:\n{err}")
                self.after(0, _err)

        threading.Thread(target=_run, daemon=True).start()

    def replace_crop(self, index):
        # Open crop window
        scene = self.session.get_all_scenes()[index]
        
        def on_crop_saved(idx, new_data, replace=True):
            if replace:
                self.session.update_scene(idx, new_data)
            else:
                # We are extracting a new sub-panel!
                # We need to create a complete scene dictionary
                import copy
                import time
                parent_scene = self.session.get_all_scenes()[idx]
                new_scene = copy.deepcopy(parent_scene)
                
                # Update with the new cropped data
                new_scene.update(new_data)
                
                # Mark as sub-panel and link parent
                new_scene["scene_id"] = f"{parent_scene['scene_id']}_sub_{int(time.time()*1000)}"
                new_scene["parent_id"] = parent_scene["scene_id"]
                new_scene["is_sub_panel"] = True
                
                # Insert it right after the parent!
                self.session.insert_scene_after(idx, new_scene)
                
            self.refresh_list()
        
        CropWindow(self, self.session, index, on_crop_saved)
        
    def show_export_validation(self):
        import time
        import os
        from tkinter import filedialog
        
        scenes = self.session.get_all_scenes()
        total = len(scenes)
        deleted = sum(1 for s in scenes if s.get("deleted"))
        modified = sum(1 for s in scenes if s.get("user_modified"))
        final_count = total - deleted
        
        msg = f"Original Images: {total}\nGenerated Scenes: {total}\nDeleted Scenes: {deleted}\nModified Scenes: {modified}\n\nFinal Export Scenes: {final_count}"
        
        dialog = ctk.CTkToplevel(self)
        dialog.title("Configure Export")
        dialog.geometry("500x500")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Export Validation", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        ctk.CTkLabel(dialog, text=msg, justify="left").pack(pady=10)
        
        # Inputs
        input_frame = ctk.CTkFrame(dialog)
        input_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(input_frame, text="Project Name:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        import os as _os
        _ep_name = _os.path.basename(self.session.project_dir)
        _series_name = _os.path.basename(_os.path.dirname(self.session.project_dir))
        proj_name_var = ctk.StringVar(value=_series_name)
        proj_name_entry = ctk.CTkEntry(input_frame, textvariable=proj_name_var, width=300)
        proj_name_entry.grid(row=0, column=1, sticky="w", padx=10, pady=10)
        
        ctk.CTkLabel(input_frame, text="CapCut Drafts Folder:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        
        default_dir = os.path.expanduser(r"~\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft")
        dir_var = ctk.StringVar(value=default_dir)
        dir_entry = ctk.CTkEntry(input_frame, textvariable=dir_var, width=220)
        dir_entry.grid(row=1, column=1, sticky="w", padx=10, pady=10)
        
        def browse_dir():
            d = filedialog.askdirectory(initialdir=dir_var.get(), title="Select CapCut Drafts Folder")
            if d:
                dir_var.set(d)
                
        ctk.CTkButton(input_frame, text="Browse", width=70, command=browse_dir).grid(row=1, column=2, padx=5, pady=10)
        
        def confirm():
            pname = proj_name_var.get().strip()
            pdir = dir_var.get().strip()
            if not pname or not pdir:
                return
            dialog.destroy()
            self.do_export(pname, pdir)
            
        ctk.CTkButton(dialog, text="Confirm & Generate Package", fg_color="green", hover_color="darkgreen", command=confirm).pack(pady=20)
        
    def do_export(self, project_name, capcut_draft_dir):
        import threading
        allowed = [anim for anim, var in self.anim_vars.items() if var.get()] if self.apply_motion_var.get() else []

        popup = ctk.CTkToplevel(self)
        popup.title("Generating CapCut Package...")
        popup.geometry("420x140")
        popup.transient(self.winfo_toplevel())
        popup.grab_set()

        ctk.CTkLabel(popup, text="Building CapCut package...\nPlease wait.",
                     font=ctk.CTkFont(size=14)).pack(pady=25)
        bar = ctk.CTkProgressBar(popup)
        bar.pack(fill="x", padx=20)
        bar.set(0)
        bar.start()

        def _run():
            try:
                exporter = Exporter(self.session)
                out_path = exporter.export_package(
                    allowed_animations=allowed,
                    project_name=project_name,
                    custom_draft_dir=capcut_draft_dir
                )
                def _ok():
                    if popup.winfo_exists():
                        bar.stop()
                        popup.destroy()
                    from tkinter import messagebox
                    messagebox.showinfo("Export Complete", f"CapCut package generated at:\n{out_path}")
                self.after(0, _ok)
            except Exception as e:
                def _err(err=str(e)):
                    if popup.winfo_exists():
                        bar.stop()
                        popup.destroy()
                    from tkinter import messagebox
                    messagebox.showerror("Export Failed", f"Could not generate package:\n{err}")
                self.after(0, _err)

        threading.Thread(target=_run, daemon=True).start()

    def load_next_episode(self):
        import os
        import threading
        from core.project_session import ProjectSession

        # --- Determine series dir and current episode ---
        # session.project_dir is e.g. â€¦/projects/oka/ep_001
        # series_dir is â€¦/projects/oka
        current_ep_dir = self.session.project_dir          # absolute path to ep folder
        series_dir = os.path.dirname(current_ep_dir)       # series folder (oka/)
        current_ep_name = os.path.basename(current_ep_dir) # 'ep_001'

        # Save current session first
        self.session.save()

        # Find all ep_XXX siblings sorted
        all_eps = sorted([
            ep for ep in os.listdir(series_dir)
            if ep.startswith("ep_") and
            os.path.exists(os.path.join(series_dir, ep, "session.json"))
        ])

        if not all_eps:
            from tkinter import messagebox
            messagebox.showerror("Error", "No episode folders found in series directory!")
            return

        try:
            current_idx = all_eps.index(current_ep_name)
        except ValueError:
            from tkinter import messagebox
            messagebox.showerror("Error", f"Could not find {current_ep_name} in series!")
            return

        # --- Append current episode to mega draft (background thread) ---
        allowed_anims = (
            [anim for anim, var in self.anim_vars.items() if var.get()]
            if self.apply_motion_var.get() else []
        )
        active_scenes = self.session.get_active_scenes()
        ep_name_snap = current_ep_name
        series_dir_snap = series_dir

        def _append_bg():
            try:
                from core.exporter import Exporter
                count = Exporter.append_to_capcut_draft(
                    series_dir_snap, ep_name_snap,
                    active_scenes, allowed_anims if allowed_anims else None
                )
                def _cb():
                    if self.winfo_exists():
                        self._capcut_draft_log(ep_name_snap, count)
                self.after(0, _cb)
            except Exception as e:
                def _err_cb(err=str(e)):
                    if self.winfo_exists():
                        self._capcut_draft_log(ep_name_snap, 0, err)
                self.after(0, _err_cb)

        threading.Thread(target=_append_bg, daemon=True).start()

        # --- Navigate ---
        if current_idx + 1 < len(all_eps):
            # Load next episode
            next_ep = all_eps[current_idx + 1]
            projects_dir = os.path.dirname(series_dir)
            series_name = os.path.basename(series_dir)
            proj_rel = f"{series_name}/{next_ep}"
            next_session = ProjectSession(projects_dir, proj_rel)
            if hasattr(self.master, "show_review_view"):
                self.master.show_review_view(next_session)
        else:
            # Last episode â€” ask about CapCut draft
            self._ask_finalize_capcut_draft(series_dir)

    def _capcut_draft_log(self, ep_name: str, count: int, error: str = None):
        """Called from main thread after background append completes."""
        if error:
            import tkinter.messagebox as mb
            mb.showwarning(
                "Mega Draft Warning",
                f"Episode {ep_name} could not be appended to mega draft:\n{error}"
            )
        else:
            print(f"[Mega Draft] {ep_name}: {count} panels appended âœ…")

    def _ask_finalize_capcut_draft(self, series_dir: str):
        """Shows Yes/No popup on last episode and creates CapCut draft if Yes."""
        import os
        from tkinter import messagebox, filedialog

        series_name = os.path.basename(series_dir)
        mega_data_path = os.path.join(series_dir, "_capcut_draft", "draft_data.json")

        # Count panels so far (includes what was just queued in bg thread)
        total_panels = "unknown"
        if os.path.exists(mega_data_path):
            try:
                import json
                with open(mega_data_path) as f:
                    d = json.load(f)
                total_panels = len(d.get("segments", []))
            except Exception:
                pass

        create = messagebox.askyesno(
            "All Episodes Reviewed! ðŸŽ‰",
            f"All episodes in '{series_name}' have been reviewed!\n\n"
            f"Panels queued in draft: {total_panels}\n\n"
            f"Create CapCut Draft now?\n"
            f"(You can also do this later from the 'Generate CapCut Package' button)"
        )

        if not create:
            self.on_back_callback()
            return

        # Ask where to save
        dialog = ctk.CTkToplevel(self)
        dialog.title("Create CapCut Draft")
        dialog.geometry("520x260")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Create Mega CapCut Draft",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=15)

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="x", padx=25)
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Project Name:").grid(row=0, column=0, sticky="w", pady=8)
        import time as _time
        name_var = ctk.StringVar(value=f"{series_name}")
        ctk.CTkEntry(form, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=10, pady=8)

        ctk.CTkLabel(form, text="CapCut Drafts Folder:").grid(row=1, column=0, sticky="w", pady=8)
        default_cc = os.path.expanduser(
            r"~\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft"
        )
        dir_var = ctk.StringVar(value=default_cc)
        ctk.CTkEntry(form, textvariable=dir_var).grid(row=1, column=1, sticky="ew", padx=10, pady=8)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=25, pady=5)

        def browse():
            d = filedialog.askdirectory(initialdir=dir_var.get())
            if d:
                dir_var.set(d)

        ctk.CTkButton(btn_row, text="Browse...", width=90, command=browse).pack(side="left")

        def confirm():
            pname = name_var.get().strip()
            pdir  = dir_var.get().strip()
            if not pname or not pdir:
                return
            dialog.destroy()
            self._run_finalize(series_dir, pname, pdir)

        ctk.CTkButton(btn_row, text="Create Draft", fg_color="green",
                      hover_color="darkgreen", command=confirm).pack(side="right")

    def _run_finalize(self, series_dir: str, project_name: str, capcut_dir: str):
        """Runs finalize_capcut_draft in a background thread with a progress popup."""
        import threading

        popup = ctk.CTkToplevel(self)
        popup.title("Creating CapCut Draft...")
        popup.geometry("400x150")
        popup.transient(self.winfo_toplevel())
        popup.grab_set()

        lbl = ctk.CTkLabel(popup, text="Building CapCut draft from all episodesâ€¦\nPlease wait.",
                           font=ctk.CTkFont(size=14))
        lbl.pack(pady=30)

        bar = ctk.CTkProgressBar(popup)
        bar.pack(fill="x", padx=20)
        bar.set(0)
        bar.start()  # indeterminate spin

        def _run():
            try:
                from core.exporter import Exporter
                out = Exporter.finalize_capcut_draft(series_dir, project_name, capcut_dir)
                def _ok():
                    bar.stop()
                    popup.destroy()
                    from tkinter import messagebox
                    messagebox.showinfo(
                        "Done! ðŸŽ¬",
                        f"CapCut draft created successfully!\n\n{out}"
                    )
                    self.on_back_callback()
                self.after(0, _ok)
            except Exception as e:
                def _err(err=str(e)):
                    bar.stop()
                    popup.destroy()
                    from tkinter import messagebox
                    messagebox.showerror("Export Failed", f"Could not create draft:\n{err}")
                self.after(0, _err)

        threading.Thread(target=_run, daemon=True).start()
