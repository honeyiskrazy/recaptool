import customtkinter as ctk
from PIL import Image
import threading
import queue
import time
import os
import random
import urllib.parse
from core.downloader import Downloader
from core.processor import Processor
from core.project_session import ProjectSession

class ProcessingView(ctk.CTkFrame):
    def __init__(self, master, on_complete_callback):
        super().__init__(master)
        self.on_complete_callback = on_complete_callback
        
        # Grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # --- Top Frame (Input & Controls) ---
        self.top_frame = ctk.CTkFrame(self, height=80)
        self.top_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)
        self.top_frame.grid_columnconfigure(3, weight=0)
        
        # Sub-frame for URL Label and Auto-Gen button
        self.url_label_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.url_label_frame.grid(row=0, column=0, padx=5, pady=10)
        
        self.url_label = ctk.CTkLabel(self.url_label_frame, text="Webtoon URL(s):")
        self.url_label.pack(anchor="w")
        
        self.auto_gen_btn = ctk.CTkButton(self.url_label_frame, text="✨ Auto-Gen URLs", width=100, height=24, fg_color="#4B0082", hover_color="#300055", command=self.open_auto_gen_popup)
        self.auto_gen_btn.pack(anchor="w", pady=(5, 0))
        
        self.load_txt_btn = ctk.CTkButton(self.url_label_frame, text="📄 Load TXT", width=100, height=24, fg_color="#006400", hover_color="#004d00", command=self.load_urls_from_txt)
        self.load_txt_btn.pack(anchor="w", pady=(5, 0))
        
        self.url_textbox = ctk.CTkTextbox(self.top_frame, height=60)
        self.url_textbox.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        self.folder_label = ctk.CTkLabel(self.top_frame, text="Folder Name:")
        self.folder_label.grid(row=0, column=2, padx=10, pady=10)
        
        self.folder_entry = ctk.CTkEntry(self.top_frame, placeholder_text="Project Folder Name", width=150)
        self.folder_entry.grid(row=0, column=3, padx=10, pady=10, sticky="w")
        
        self.height_dropdown = ctk.CTkComboBox(self.top_frame, values=[f"{i}px" for i in range(1000, 6500, 500)], width=80)
        self.height_dropdown.set("2500px")
        self.height_dropdown.grid(row=0, column=4, padx=5, pady=10)

        self.start_button = ctk.CTkButton(self.top_frame, text="Start Processing", command=self.start_processing)
        self.start_button.grid(row=0, column=5, padx=5, pady=10)

        # ── Row 1: extra processing controls ────────────────────────────────
        extra_row = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        extra_row.grid(row=1, column=0, columnspan=9, padx=5, pady=(0, 8), sticky="w")

        ctk.CTkLabel(extra_row, text="Min Panel Height:").pack(side="left", padx=(8, 2))
        self.min_height_entry = ctk.CTkEntry(extra_row, placeholder_text="300", width=60)
        self.min_height_entry.insert(0, "300")
        self.min_height_entry.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(extra_row, text="Short Panel:").pack(side="left", padx=(0, 2))
        self.short_panel_combo = ctk.CTkComboBox(
            extra_row,
            values=["Flag", "Keep", "Merge Next", "Skip"],
            width=110,
            state="readonly"
        )
        self.short_panel_combo.set("Flag")
        self.short_panel_combo.pack(side="left", padx=(0, 16))

        self.upscale_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(extra_row, text="2× Upscale (Lanczos + Sharpen)", variable=self.upscale_var).pack(side="left", padx=(0, 8))
        
        self.cancel_button = ctk.CTkButton(self.top_frame, text="Cancel", fg_color="red", hover_color="darkred", state="disabled", command=self.cancel_processing)
        self.cancel_button.grid(row=0, column=6, padx=5, pady=10)
        
        self.restart_button = ctk.CTkButton(self.top_frame, text="Restart", fg_color="orange", hover_color="darkorange", command=self.restart_processing)
        self.restart_button.grid(row=0, column=7, padx=5, pady=10)
        
        self.history_btn = ctk.CTkButton(self.top_frame, text="Project History", fg_color="gray", hover_color="darkgray", command=self.show_history)
        self.history_btn.grid(row=0, column=8, padx=5, pady=10)
        
        
        # --- Middle Frame (Dashboard, Logs & Preview) ---
        self.mid_frame = ctk.CTkFrame(self)
        self.mid_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.mid_frame.grid_columnconfigure(0, weight=1)
        self.mid_frame.grid_columnconfigure(1, weight=2)
        self.mid_frame.grid_rowconfigure(0, weight=0)
        self.mid_frame.grid_rowconfigure(1, weight=1)
        
        # Dashboard Stats Panel
        self.stats_frame = ctk.CTkFrame(self.mid_frame)
        self.stats_frame.grid(row=0, column=0, padx=10, pady=10, sticky="new")
        self.stats_frame.grid_columnconfigure(1, weight=1)
        
        # System Stats (Top)
        self.sys_stats_label = ctk.CTkLabel(self.stats_frame, text="⚙️ CPU: --% | RAM: --% | GPU: --", font=ctk.CTkFont(size=12, weight="bold"))
        self.sys_stats_label.grid(row=0, column=0, columnspan=2, pady=(10, 5))
        
        ctk.CTkLabel(self.stats_frame, text="Live Dashboard", font=ctk.CTkFont(size=16, weight="bold")).grid(row=1, column=0, columnspan=2, pady=(5, 5))
        
        self.stat_target_val = ctk.CTkLabel(self.stats_frame, text="-", text_color="#2FA572", font=ctk.CTkFont(weight="bold"))
        ctk.CTkLabel(self.stats_frame, text="Current Target Episode:").grid(row=2, column=0, padx=10, pady=2, sticky="w")
        self.stat_target_val.grid(row=2, column=1, padx=10, pady=2, sticky="e")

        self.stat_status_val = ctk.CTkLabel(self.stats_frame, text="Idle")
        ctk.CTkLabel(self.stats_frame, text="Current Phase:").grid(row=3, column=0, padx=10, pady=2, sticky="w")
        self.stat_status_val.grid(row=3, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_episodes_val = ctk.CTkLabel(self.stats_frame, text="0 / 0")
        ctk.CTkLabel(self.stats_frame, text="Batch Episodes:").grid(row=4, column=0, padx=10, pady=2, sticky="w")
        self.stat_episodes_val.grid(row=4, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_slices_val = ctk.CTkLabel(self.stats_frame, text="0")
        ctk.CTkLabel(self.stats_frame, text="Total Slices Downloaded:").grid(row=5, column=0, padx=10, pady=2, sticky="w")
        self.stat_slices_val.grid(row=5, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_images_val = ctk.CTkLabel(self.stats_frame, text="0")
        ctk.CTkLabel(self.stats_frame, text="Total Panels Extracted:").grid(row=6, column=0, padx=10, pady=2, sticky="w")
        self.stat_images_val.grid(row=6, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_speed_val = ctk.CTkLabel(self.stats_frame, text="-")
        ctk.CTkLabel(self.stats_frame, text="Processing Speed:").grid(row=7, column=0, padx=10, pady=2, sticky="w")
        self.stat_speed_val.grid(row=7, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_errors_val = ctk.CTkLabel(self.stats_frame, text="0", text_color="#ff4444")
        ctk.CTkLabel(self.stats_frame, text="Errors / Skipped:").grid(row=8, column=0, padx=10, pady=2, sticky="w")
        self.stat_errors_val.grid(row=8, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_storage_val = ctk.CTkLabel(self.stats_frame, text="-")
        ctk.CTkLabel(self.stats_frame, text="Project Storage Used:").grid(row=9, column=0, padx=10, pady=2, sticky="w")
        self.stat_storage_val.grid(row=9, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_time_val = ctk.CTkLabel(self.stats_frame, text="00:00")
        ctk.CTkLabel(self.stats_frame, text="Batch Time Elapsed:").grid(row=10, column=0, padx=10, pady=2, sticky="w")
        self.stat_time_val.grid(row=10, column=1, padx=10, pady=2, sticky="e")
        
        self.stat_eta_val = ctk.CTkLabel(self.stats_frame, text="--:--")
        ctk.CTkLabel(self.stats_frame, text="Batch Est. Time Left:").grid(row=11, column=0, padx=10, pady=2, sticky="w")
        self.stat_eta_val.grid(row=11, column=1, padx=10, pady=2, sticky="e")
        
        self.update_sys_stats_loop()
        self.update_storage_loop()
        
        # Log Panel
        self.log_textbox = ctk.CTkTextbox(self.mid_frame, state="disabled", font=ctk.CTkFont(size=14))
        self.log_textbox.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        # Preview Panel
        self.preview_frame = ctk.CTkFrame(self.mid_frame)
        self.preview_frame.grid(row=0, column=1, rowspan=2, padx=10, pady=10, sticky="nsew")
        self.preview_frame.grid_rowconfigure(1, weight=1)
        self.preview_frame.grid_columnconfigure((0,1), weight=1)
        
        ctk.CTkLabel(self.preview_frame, text="Original Scene").grid(row=0, column=0, pady=(10,0))
        ctk.CTkLabel(self.preview_frame, text="Cleaned Scene").grid(row=0, column=1, pady=(10,0))
        
        self.original_preview_label = ctk.CTkLabel(self.preview_frame, text="")
        self.original_preview_label.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        
        self.cleaned_preview_label = ctk.CTkLabel(self.preview_frame, text="")
        self.cleaned_preview_label.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")
        
        self.orig_name_label = ctk.CTkLabel(self.preview_frame, text="", font=ctk.CTkFont(size=11, slant="italic"))
        self.orig_name_label.grid(row=2, column=0, pady=(0, 5))
        
        self.clean_name_label = ctk.CTkLabel(self.preview_frame, text="", font=ctk.CTkFont(size=11, slant="italic"))
        self.clean_name_label.grid(row=2, column=1, pady=(0, 5))
        
        self.nav_frame = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        self.nav_frame.grid(row=3, column=0, columnspan=2, pady=5)
        
        self.prev_btn = ctk.CTkButton(self.nav_frame, text="< Prev", width=60, command=self.preview_prev, state="disabled")
        self.prev_btn.pack(side="left", padx=5)
        
        self.preview_info_label = ctk.CTkLabel(self.nav_frame, text="Auto-following live", width=150)
        self.preview_info_label.pack(side="left", padx=10)
        
        self.next_btn = ctk.CTkButton(self.nav_frame, text="Next >", width=60, command=self.preview_next, state="disabled")
        self.next_btn.pack(side="left", padx=5)
        
        # --- Bottom Frame (Progress) ---
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        
        self.progress_bar = ctk.CTkProgressBar(self.bottom_frame)
        self.progress_bar.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.progress_bar.set(0)
        
        self.review_button = ctk.CTkButton(
            self.bottom_frame,
            text="Go to Manual Review",
            state="disabled",
            command=self.go_to_review)
        self.review_button.grid(row=0, column=1, padx=10, pady=10)

        self.script_tool_btn = ctk.CTkButton(
            self.bottom_frame,
            text="📝 Open Script Tool",
            fg_color="#5A4EA3", hover_color="#3D3575",
            command=self._open_script_tool)
        self.script_tool_btn.grid(row=0, column=2, padx=10, pady=10)
        
        # --- Logic variables ---
        self.ui_queue = queue.Queue()
        self.is_processing = False
        self._cancel_event = threading.Event()
        self.start_time = 0
        self.project_session = None
        
        self.preview_history = []
        self.preview_index = -1
        self.auto_follow = True
        
        self.after(100, self.process_queue)

    def update_sys_stats_loop(self):
        try:
            if not self.winfo_exists(): return
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
            self.sys_stats_label.configure(text=f"⚙️ CPU: {cpu}% | RAM: {ram}% | GPU: {gpu_text}")
        except Exception:
            pass
        try:
            if self.winfo_exists():
                self.after(2000, self.update_sys_stats_loop)
        except Exception:
            pass

    def update_storage_loop(self):
        try:
            if not self.winfo_exists(): return
            if self.is_processing and self.project_session:
                import os
                
                # Get size of the series base folder
                series_dir = os.path.dirname(self.project_session.project_dir)
                total_size = 0
                for dirpath, _, filenames in os.walk(series_dir):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if not os.path.islink(fp):
                            total_size += os.path.getsize(fp)
                            
                # Convert to MB
                mb = total_size / (1024 * 1024)
                if mb > 1024:
                    self.stat_storage_val.configure(text=f"{mb/1024:.2f} GB")
                else:
                    self.stat_storage_val.configure(text=f"{mb:.1f} MB")
        except Exception:
            pass
            
        try:
            if self.winfo_exists():
                self.after(5000, self.update_storage_loop)
        except Exception:
            pass

    def load_urls_from_txt(self):
        import tkinter.filedialog as filedialog
        filepath = filedialog.askopenfilename(
            title="Select Text File with URLs",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Filter out empty lines
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                
                # Overwrite textbox
                self.url_textbox.delete("1.0", "end")
                self.url_textbox.insert("1.0", '\n'.join(lines))
                
                # Display success
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", f"Loaded {len(lines)} URLs from {os.path.basename(filepath)}\n")
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")
            except Exception as e:
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", f"Error loading text file: {e}\n")
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")

    def open_auto_gen_popup(self):
        base_url = self.url_textbox.get("1.0", "end").strip().split('\n')[0].strip()
        
        if not base_url:
            import tkinter.messagebox as mb
            mb.showerror("Error", "Please paste a Series Link in the text box first!")
            return
            
        import threading
        
        # Show fetching popup
        popup = ctk.CTkToplevel(self)
        popup.title("Fetching Chapters...")
        popup.geometry("400x200")
        popup.grab_set()
        
        lbl = ctk.CTkLabel(popup, text="Connecting to website and fetching chapters...\nPlease wait.", font=ctk.CTkFont(size=14))
        lbl.pack(pady=40)
        
        def fetch_task():
            try:
                from core.series_scraper import SeriesScraper
                scraper = SeriesScraper()
                links = scraper.fetch_chapters(base_url)
                
                if not links:
                    self.after(0, lambda: self._show_fetch_error(popup, "Could not find any chapter links on this page."))
                    return
                    
                self.after(0, lambda: self._show_fetch_success(popup, links))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self._show_fetch_error(popup, msg))
                
        threading.Thread(target=fetch_task, daemon=True).start()

    def _show_fetch_error(self, popup, error_msg):
        popup.destroy()
        import tkinter.messagebox as mb
        mb.showerror("Fetch Failed", f"Error fetching chapters:\n\n{error_msg}")

    def _show_fetch_success(self, popup, links):
        # Clear the fetching layout
        for widget in popup.winfo_children():
            widget.destroy()
            
        popup.title("Select Chapters")
        popup.geometry("500x350")
        
        ctk.CTkLabel(popup, text=f"🎉 Found {len(links)} Chapters!", font=ctk.CTkFont(weight="bold", size=18), text_color="#2FA572").pack(pady=(15, 5))
        ctk.CTkLabel(popup, text="Select the range of chapters you want to download:").pack(pady=5)
        
        range_frame = ctk.CTkFrame(popup, fg_color="transparent")
        range_frame.pack(pady=15)
        
        ctk.CTkLabel(range_frame, text="From Chapter:").pack(side="left", padx=5)
        
        # Determine the numbers for dropdowns based on index (1 to N)
        # Since websites might have chapter 0 or prologue, we just use 1 to N logic
        options = [str(i+1) for i in range(len(links))]
        
        start_dropdown = ctk.CTkComboBox(range_frame, values=options, width=80)
        start_dropdown.set(options[0])
        start_dropdown.pack(side="left", padx=5)
        
        ctk.CTkLabel(range_frame, text="To Chapter:").pack(side="left", padx=5)
        
        end_dropdown = ctk.CTkComboBox(range_frame, values=options, width=80)
        
        # Default to a batch of 10 or max available
        default_end = min(10, len(links))
        end_dropdown.set(options[default_end - 1])
        end_dropdown.pack(side="left", padx=5)
        
        def insert_links():
            try:
                s_idx = int(start_dropdown.get()) - 1
                e_idx = int(end_dropdown.get()) - 1
                
                if s_idx > e_idx:
                    s_idx, e_idx = e_idx, s_idx # Swap if they put them backwards
                    
                selected_links = links[s_idx:e_idx + 1]
                
                self.url_textbox.configure(state="normal")
                self.url_textbox.delete("1.0", "end")
                self.url_textbox.insert("end", "\n".join(selected_links))
                popup.destroy()
            except ValueError:
                import tkinter.messagebox as mb
                mb.showerror("Error", "Please select valid numbers from the dropdown.")
        
        ctk.CTkButton(popup, text="✨ Insert into Queue", command=insert_links, fg_color="#4B0082", hover_color="#300055").pack(pady=20)

    def log(self, message: str):
        self.ui_queue.put({"type": "log", "msg": message})
        
    def update_stats(self, phase: str = None, processed: int = None, total: int = None, target: str = None, errors: int = None):
        data = {"type": "stats"}
        if phase is not None: data["phase"] = phase
        if processed is not None: data["processed"] = processed
        if total is not None: data["total"] = total
        if target is not None: data["target"] = target
        if errors is not None: data["errors"] = errors
        self.ui_queue.put(data)
        
    def update_progress(self, progress: float):
        self.ui_queue.put({"type": "progress", "val": progress})
        
    def preview_prev(self):
        if self.preview_index > 0:
            self.preview_index -= 1
            self.auto_follow = False
            self._render_current_preview()
            
    def preview_next(self):
        if self.preview_index < len(self.preview_history) - 1:
            self.preview_index += 1
            if self.preview_index == len(self.preview_history) - 1:
                self.auto_follow = True
            self._render_current_preview()
            
    def show_history(self):
        import os
        import json
        
        dialog = ctk.CTkToplevel(self)
        dialog.title("Recent Projects")
        dialog.geometry("500x600")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Project History", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=20)
        
        scroll_frame = ctk.CTkScrollableFrame(dialog)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        projects_dir = os.path.join(os.getcwd(), "projects")
        
        if not os.path.exists(projects_dir):
            os.makedirs(projects_dir)

        # NEW: find series folders (support both new nested and old flat formats)
        series_list = []
        for d in sorted(os.listdir(projects_dir)):
            series_path = os.path.join(projects_dir, d)
            if not os.path.isdir(series_path):
                continue
                
            # Check for new nested format (ep_XXX subfolders)
            ep_dirs = sorted([
                ep for ep in os.listdir(series_path)
                if ep.startswith("ep_") and
                os.path.exists(os.path.join(series_path, ep, "session.json"))
            ])
            
            if ep_dirs:
                first_ep = ep_dirs[0]
                latest_mtime = max(
                    os.path.getmtime(os.path.join(series_path, ep, "session.json"))
                    for ep in ep_dirs
                )
                series_list.append((d, first_ep, latest_mtime, len(ep_dirs)))
            else:
                # Check for old flat format (session.json right in the series folder)
                old_session_path = os.path.join(series_path, "session.json")
                if os.path.exists(old_session_path):
                    latest_mtime = os.path.getmtime(old_session_path)
                    series_list.append((d, "", latest_mtime, 1))

        # Sort by most recently modified
        series_list.sort(key=lambda x: x[2], reverse=True)
        
        if not series_list:
            ctk.CTkLabel(scroll_frame, text="No previous projects found.").pack(pady=20)
            
        for series_name, first_ep, _, ep_count in series_list:
            label = f"{series_name}  ({ep_count} episode{'s' if ep_count != 1 else ''})"
            btn = ctk.CTkButton(
                scroll_frame, text=label, height=40,
                command=lambda sn=series_name, fe=first_ep: self.load_project(sn, fe, dialog)
            )
            btn.pack(fill="x", padx=10, pady=5)
            
        def clear_history():
            import shutil
            for d in os.listdir(projects_dir):
                p = os.path.join(projects_dir, d)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
            dialog.destroy()
            self.show_history()
            
        ctk.CTkButton(dialog, text="Clear All History", fg_color="red", hover_color="darkred", command=clear_history).pack(pady=20)


    def load_project(self, series_name: str, episode_name: str, dialog):
        """Load a specific episode from the nested folder structure or fallback to flat."""
        dialog.destroy()
        from core.project_session import ProjectSession
        import os
        
        # If episode_name exists, it's the new nested format 'series/ep_XXX'
        # Otherwise, it's the old flat format 'series'
        if episode_name:
            proj_rel = f"{series_name}/{episode_name}"
        else:
            proj_rel = series_name
            
        session = ProjectSession(os.path.join(os.getcwd(), "projects"), proj_rel)
        self.on_complete_callback(session)
            
    def _render_current_preview(self):
        if not self.preview_history or self.preview_index < 0:
            return
            
        orig_path, clean_path = self.preview_history[self.preview_index]
        self.update_image_display(orig_path, clean_path)
        
        self.prev_btn.configure(state="normal" if self.preview_index > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.preview_index < len(self.preview_history) - 1 else "disabled")
        
        status_text = "Live" if self.auto_follow else f"History: {self.preview_index + 1}/{len(self.preview_history)}"
        self.preview_info_label.configure(text=status_text)
        
    def update_image_display(self, orig_path: str, cleaned_path: str):
        try:
            import os
            orig_name = os.path.basename(orig_path)
            clean_name = os.path.basename(cleaned_path)
            
            orig_img = Image.open(orig_path)
            clean_img = Image.open(cleaned_path)
            orig_img.thumbnail((450, 650))
            clean_img.thumbnail((450, 650))
            ctk_orig = ctk.CTkImage(light_image=orig_img, dark_image=orig_img, size=orig_img.size)
            ctk_clean = ctk.CTkImage(light_image=clean_img, dark_image=clean_img, size=clean_img.size)
            self.original_preview_label.configure(image=ctk_orig, text="")
            self.cleaned_preview_label.configure(image=ctk_clean, text="")
            self.orig_name_label.configure(text=orig_name)
            self.clean_name_label.configure(text=clean_name)
        except Exception:
            pass

    def update_preview(self, orig_path: str, cleaned_path: str):
        self.ui_queue.put({"type": "preview", "orig": orig_path, "clean": cleaned_path})
        
    def format_time(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"
        
    def process_queue(self):
        if self.is_processing and getattr(self, 'batch_start_time', 0) > 0:
            elapsed = time.time() - self.batch_start_time
            self.stat_time_val.configure(text=self.format_time(elapsed))
            
        while not self.ui_queue.empty():
            try:
                item = self.ui_queue.get_nowait()
                if item["type"] == "log":
                    self.log_textbox.configure(state="normal")
                    self.log_textbox.insert("end", item["msg"] + "\n")
                    self.log_textbox.see("end")
                    self.log_textbox.configure(state="disabled")
                
                elif item["type"] == "stats":
                    if "phase" in item:
                        phase = item["phase"]
                        if getattr(self, 'current_phase', '') != phase:
                            self.phase_start_time = time.time()
                            self.stat_speed_val.configure(text="-")
                        self.stat_status_val.configure(text=phase)
                        self.current_phase = phase
                    if "target" in item:
                        self.stat_target_val.configure(text=item["target"])
                    if "errors" in item:
                        self.batch_errors += item["errors"]
                        self.stat_errors_val.configure(text=str(self.batch_errors))
                    if "processed" in item and "total" in item:
                        processed = item["processed"]
                        total = item["total"]
                        phase = getattr(self, 'current_phase', '')
                        
                        # Accumulate totals for batch
                        if "download" in phase.lower():
                            base_dl = getattr(self, 'batch_accum_dl', 0)
                            self.stat_slices_val.configure(text=f"{base_dl + processed} / {base_dl + total}")
                            if processed > 0 and hasattr(self, 'phase_start_time'):
                                p_elapsed = time.time() - self.phase_start_time
                                if p_elapsed > 0:
                                    self.stat_speed_val.configure(text=f"{processed / p_elapsed:.1f} slices/sec")
                        elif "extract" in phase.lower() or "process" in phase.lower():
                            base_ext = getattr(self, 'batch_accum_ext', 0)
                            self.stat_images_val.configure(text=f"{base_ext + processed} / {base_ext + total}")
                            if processed > 0 and hasattr(self, 'phase_start_time'):
                                p_elapsed = time.time() - self.phase_start_time
                                if p_elapsed > 0:
                                    self.stat_speed_val.configure(text=f"{processed / p_elapsed:.1f} panels/sec")
                            
                        if processed > 0 and getattr(self, 'batch_start_time', 0) > 0 and total > 0:
                            elapsed = time.time() - self.batch_start_time
                            batch_total = getattr(self, 'batch_total', 1)
                            batch_current = getattr(self, 'batch_current', 0)
                            
                            # Fractional progress of the entire batch
                            current_progress = batch_current + (processed / total)
                            if current_progress > 0:
                                avg_time_per_ep = elapsed / current_progress
                                remaining_progress = batch_total - current_progress
                                eta_seconds = remaining_progress * avg_time_per_ep
                                self.stat_eta_val.configure(text=self.format_time(eta_seconds))
                        
                elif item["type"] == "progress":
                    self.progress_bar.set(item["val"])
                    
                elif item["type"] == "preview":
                    try:
                        orig_path = item["orig"]
                        clean_path = item["clean"]
                        self.preview_history.append((orig_path, clean_path))
                        
                        if self.auto_follow:
                            self.preview_index = len(self.preview_history) - 1
                            self._render_current_preview()
                    except Exception as e:
                        print(f"Preview error: {e}")
                        
                elif item["type"] == "done":
                    self.is_processing = False
                    self.is_cancelled = False
                    
                    if item.get("cancelled", False):
                        self.log("Batch processing cancelled.")
                        self.start_button.configure(state="normal")
                        self.cancel_button.configure(state="disabled", text="Cancel")
                        self.review_button.configure(state="disabled")
                        self.stat_status_val.configure(text="Processing Cancelled")
                        self.stat_eta_val.configure(text="00:00")
                        self.batch_queue = [] # clear queue
                    else:
                        # If there are more items in the batch, process the next one!
                        if getattr(self, 'batch_queue', []):
                            self.accumulate_batch_totals()
                            self.process_next_in_batch()
                        else:
                            # The entire batch is finished!
                            self.start_button.configure(state="normal")
                            self.cancel_button.configure(state="disabled", text="Cancel")
                            is_single = getattr(self, 'batch_total', 1) == 1
                            self.review_button.configure(state="normal")
                            self.stat_status_val.configure(text="Batch Complete" if not is_single else "Ready for Review")
                            self.stat_eta_val.configure(text="00:00")
                            
                            self.log("\n==================================================")
                            self.log("✨ PROCESSING COMPLETE ✨")
                            self.log("All episodes downloaded successfully.")
                            self.log("Click 'Go to Manual Review' or 'Project History' to review them.")
                            self.log("==================================================\n")
            except queue.Empty:
                break
        
        self.after(100, self.process_queue)

    def accumulate_batch_totals(self):
        # Accumulate completed episode stats
        try:
            dl_text = self.stat_slices_val.cget("text")
            ext_text = self.stat_images_val.cget("text")
            
            dl_total = int(dl_text.split(" / ")[1]) if " / " in dl_text else 0
            ext_total = int(ext_text.split(" / ")[1]) if " / " in ext_text else 0
            
            self.batch_accum_dl = dl_total
            self.batch_accum_ext = ext_total
        except Exception:
            pass

    def start_processing(self):
        urls_text = self.url_textbox.get("1.0", "end-1c").strip()
        urls = [u.strip() for u in urls_text.split('\n') if u.strip()]
        folder_name = self.folder_entry.get().strip()
        
        if not urls:
            self.log("Error: URL cannot be empty.")
            return
            
        if not folder_name:
            self.log("Error: Folder Name is required. Please enter a folder name before proceeding.")
            return
            
        try:
            self.current_max_height = int(self.height_dropdown.get().replace("px", ""))
        except Exception:
            self.current_max_height = 2500

        try:
            self.current_min_height = int(self.min_height_entry.get().strip())
        except Exception:
            self.current_min_height = 300

        self.current_short_panel_behavior = self.short_panel_combo.get()
        self.current_upscale = self.upscale_var.get()
            
        if getattr(self, 'is_processing', False):
            return
            
        self.batch_queue = urls
        self.base_folder_name = folder_name
        self.batch_total = len(urls)
        self.batch_current = 0
        self.first_batch_session = None
        
        self.batch_start_time = time.time()
        self.batch_accum_dl = 0
        self.batch_accum_ext = 0
        self.batch_errors = 0
        self.stat_errors_val.configure(text="0")
        
        self.stat_episodes_val.configure(text=f"0 / {self.batch_total}")
        self.stat_slices_val.configure(text="0 / 0")
        self.stat_images_val.configure(text="0 / 0")
        
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal", text="Cancel")
        self.review_button.configure(state="disabled")
        
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        
        self.process_next_in_batch()

    def process_next_in_batch(self):
        if not self.batch_queue:
            return
            
        self.batch_current += 1
        url = self.batch_queue.pop(0)
        
        # NEW: nested folder path — projects/oka/ep_001, ep_002, ...
        ep_num = f"ep_{self.batch_current:03d}"
        if self.batch_total == 1:
            # Single episode — still uses nested: series/ep_001
            current_folder = f"{self.base_folder_name}/{ep_num}"
        else:
            current_folder = f"{self.base_folder_name}/{ep_num}"
            self.log(f"\n--- BATCH {self.batch_current}/{self.batch_total} ---")
            self.log(f"Processing URL: {url}")
            self.log(f"Saving to Folder: {current_folder}")
            
        self.is_processing = True
        self._cancel_event.clear()
        self.start_time = time.time()
        
        # Determine the target episode display name
        ep_num = f"ep_{self.batch_current:03d}"
        target_display = ep_num if self.batch_total == 1 else f"{self.base_folder_name} ({ep_num})"
        
        self.stat_episodes_val.configure(text=f"{self.batch_current} / {self.batch_total}")
        self.update_stats(phase="Initializing", processed=0, total=0, target=target_display)
        self.progress_bar.set(0)
        self.preview_history = []
        self.preview_index = -1
        
        threading.Thread(target=self.worker, args=(url, current_folder), daemon=True).start()


    def restart_processing(self):
        if self.is_processing:
            self.cancel_processing()
            
        folder_name = self.folder_entry.get().strip()
        if not folder_name:
            self.log("Nothing to restart. Folder Name is empty.")
            return
            
        import shutil
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Wipe the series folder (projects/oka/)
        project_dir = os.path.join(base_dir, "projects", folder_name)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
            self.log(f"Deleted series folder: {folder_name}")
            
        # Wipe workspace folder
        workspace_dir = os.path.join(os.getcwd(), "workspace")
        if os.path.exists(workspace_dir):
            shutil.rmtree(workspace_dir, ignore_errors=True)
            self.log("Cleared temporary workspace.")
            
        # Reset UI
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        
        self.stat_status_val.configure(text="Initializing...")
        self.stat_eta_val.configure(text="--:--")
        self.stat_episodes_val.configure(text=f"{self.batch_current + 1} / {self.batch_total}")
        self.progress_bar.set(0)
        self.stat_time_val.configure(text="-")
        
        self.progress_bar.set(0)
        self.preview_history = []
        self.preview_index = -1
        self.original_preview_label.configure(image="", text="")
        self.cleaned_preview_label.configure(image="", text="")
        self.orig_name_label.configure(text="")
        self.clean_name_label.configure(text="")
        
        self.preview_info_label.configure(text="Auto-following live")
        self.prev_btn.configure(state="disabled")
        self.next_btn.configure(state="disabled")
        
        self.start_button.configure(state="normal")
        self.review_button.configure(state="disabled")
        
        self.log("Project restarted. All previous processing data for this folder has been deleted.")

    def worker(self, url: str, folder_name: str):
        try:
            self.log("Initializing Downloader...")
            downloader = Downloader()
            
            self.update_stats(phase="Loading AI Models (LaMa/EasyOCR)")
            self.log("Initializing AI Models...")
            max_h = getattr(self, 'current_max_height', 2500)
            processor = Processor(max_height=max_h)
            
            domain = urllib.parse.urlparse(url).netloc
            proj_name = folder_name
            # The base directory is the project workspace root
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # Use a "projects" folder to keep things tidy
            projects_dir = os.path.join(base_dir, "projects")
            os.makedirs(projects_dir, exist_ok=True)
            
            # proj_name is already 'oka/ep_001' from process_next_in_batch
            self.project_session = ProjectSession(projects_dir, proj_name)
            if getattr(self, 'batch_current', 1) == 1:
                self.first_batch_session = self.project_session
                
            project_dir = self.project_session.project_dir
            
            raw_dir = os.path.join(project_dir, "raw")
            cleaned_dir = os.path.join(project_dir, "cleaned")
            os.makedirs(raw_dir, exist_ok=True)
            os.makedirs(cleaned_dir, exist_ok=True)
            
            self.update_stats(phase="Fetching Chapter Data")
            self.log("Scraping image URLs from page...")
            image_urls = downloader.extract_image_urls(url)
            total_images = len(image_urls)
            self.log(f"Found {total_images} images to process.")
            self.update_stats(processed=0, total=total_images)
            
            self.update_stats(phase="Downloading Raw Slices")
            downloaded_slices = []
            for i, img_url in enumerate(image_urls):
                if self._cancel_event.is_set():
                    self.log("Process cancelled by user.")
                    self.ui_queue.put({"type": "done", "cancelled": True})
                    return
                    
                self.update_progress(i / total_images)
                self.update_stats(processed=i+1, total=total_images)
                
                raw_path = os.path.join(raw_dir, f"slice_{i:04d}.jpg")
                self.log(f"[{i+1}/{total_images}] Downloading slice...")
                downloader.download_image(img_url, raw_path)
                downloaded_slices.append(raw_path)
                
            self.update_stats(phase="Extracting Panels", processed=0, total=total_images)
            self.log("Detecting and extracting panels from slices...")
            self.update_progress(0.0)
            
            # Use OpenCV to save extracted panels into raw_dir
            import cv2
            all_panels = []
            
            # Extract panels from the combined stitched slices
            panels = processor.extract_panels(downloaded_slices)
            total_extracted = len(panels)
            for idx, p in enumerate(panels):
                panel_path = os.path.join(raw_dir, f"raw_{idx:04d}.jpg")
                cv2.imwrite(panel_path, p)
                all_panels.append(panel_path)
                if total_extracted > 0:
                    self.update_progress(idx / total_extracted)
                    self.update_stats(processed=idx+1, total=total_extracted)
                    
            total_panels = len(all_panels)
            self.log(f"Extracted {total_panels} individual panels!")
            
            self.update_stats(phase="Processing Panels", processed=0, total=total_panels)
            pending_scenes = []
            min_h = getattr(self, 'current_min_height', 300)
            short_behavior = getattr(self, 'current_short_panel_behavior', 'Flag')
            do_upscale = getattr(self, 'current_upscale', False)
            _merge_buffer = None  # holds panel waiting to be merged with next

            for i, panel_path in enumerate(all_panels):
                if self._cancel_event.is_set():
                    if _merge_buffer is not None:
                        pending_scenes.append(_merge_buffer)
                        _merge_buffer = None
                    if pending_scenes:
                        self.project_session.add_scenes_batch(pending_scenes)
                    self.log("Process cancelled by user.")
                    self.ui_queue.put({"type": "done", "cancelled": True})
                    return

                self.update_progress(i / total_panels)

                clean_path = os.path.join(cleaned_dir, f"{i:04d}.jpg")
                self.log(f"[{i+1}/{total_panels}] Processing (OCR & Inpainting)...")

                try:
                    process_result = processor.process_image(panel_path, clean_path, upscale=do_upscale)

                    panel_height = process_result["crop_dimensions"][1]
                    is_short = panel_height < min_h

                    # Apply short-panel behavior
                    if is_short and short_behavior == "Skip":
                        self.log(f"  -> Short panel ({panel_height}px < {min_h}px): Skipped.")
                        self.update_stats(processed=i+1, total=total_panels)
                        self.update_preview(panel_path, clean_path)
                        continue

                    if is_short and short_behavior == "Merge Next":
                        self.log(f"  -> Short panel ({panel_height}px): buffering for merge with next.")
                        if _merge_buffer is None:
                            _merge_buffer = {
                                "scene_id": f"scene_{i:04d}",
                                "source_url": url,
                                "source_site": domain,
                                "original_image_path": panel_path,
                                "cleaned_image_path": clean_path,
                                "ocr_text": process_result["ocr_text"],
                                "motion_preset_applied": None,
                                "crop_dimensions": process_result["crop_dimensions"],
                                "processing_status": "done",
                                "user_modified": False,
                                "deleted": False,
                                "suggested_for_deletion": False
                            }
                        else:
                            # Already have a buffered panel — merge both and flush
                            import cv2 as _cv2
                            import numpy as _np
                            img_a = _cv2.imread(_merge_buffer["cleaned_image_path"])
                            img_b = _cv2.imread(clean_path)
                            if img_a is not None and img_b is not None:
                                if img_a.shape[1] != img_b.shape[1]:
                                    img_b = _cv2.resize(img_b, (img_a.shape[1], img_b.shape[0]))
                                merged = _np.vstack((img_a, img_b))
                                _cv2.imwrite(_merge_buffer["cleaned_image_path"], merged)
                                _merge_buffer["crop_dimensions"] = [merged.shape[1], merged.shape[0]]
                                _merge_buffer["ocr_text"] += process_result["ocr_text"]
                            pending_scenes.append(_merge_buffer)
                            _merge_buffer = None
                        self.update_stats(processed=i+1, total=total_panels)
                        self.update_preview(panel_path, clean_path)
                        continue

                    # If we have a merge buffer and current panel is tall enough, merge and flush
                    if _merge_buffer is not None:
                        import cv2 as _cv2
                        import numpy as _np
                        img_a = _cv2.imread(_merge_buffer["cleaned_image_path"])
                        img_b = _cv2.imread(clean_path)
                        if img_a is not None and img_b is not None:
                            if img_a.shape[1] != img_b.shape[1]:
                                img_b = _cv2.resize(img_b, (img_a.shape[1], img_b.shape[0]))
                            merged = _np.vstack((img_a, img_b))
                            _cv2.imwrite(_merge_buffer["cleaned_image_path"], merged)
                            _merge_buffer["crop_dimensions"] = [merged.shape[1], merged.shape[0]]
                            _merge_buffer["ocr_text"] += process_result["ocr_text"]
                        pending_scenes.append(_merge_buffer)
                        _merge_buffer = None
                        self.update_stats(processed=i+1, total=total_panels)
                        self.update_preview(panel_path, clean_path)
                        continue

                    auto_flag = process_result["suggested_for_deletion"]
                    if is_short and short_behavior == "Flag":
                        auto_flag = True
                        self.log(f"  -> Short panel ({panel_height}px < {min_h}px): flagged for review.")

                    scene_data = {
                        "scene_id": f"scene_{i:04d}",
                        "source_url": url,
                        "source_site": domain,
                        "original_image_path": panel_path,
                        "cleaned_image_path": clean_path,
                        "ocr_text": process_result["ocr_text"],
                        "motion_preset_applied": None,
                        "crop_dimensions": process_result["crop_dimensions"],
                        "processing_status": "done",
                        "user_modified": False,
                        "deleted": False,
                        "suggested_for_deletion": auto_flag
                    }

                    pending_scenes.append(scene_data)

                    if len(pending_scenes) >= 10:
                        self.project_session.add_scenes_batch(pending_scenes)
                        pending_scenes = []

                except Exception as e:
                    self.log(f"Error processing panel {i}: {e}")
                    self.update_stats(errors=1)

                self.update_stats(processed=i+1, total=total_panels)
                self.update_preview(panel_path, clean_path)

            # Flush any remaining merge buffer
            if _merge_buffer is not None:
                pending_scenes.append(_merge_buffer)

            if pending_scenes:
                self.project_session.add_scenes_batch(pending_scenes)
                
            self.update_stats(phase="Ready For Review")
            self.update_progress(1.0)
            self.log("DONE. Ready for manual review.")
            self.current_session = self.project_session
            self.ui_queue.put({"type": "done"})
            
        except Exception as e:
            self.log(f"CRITICAL ERROR: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
            self.ui_queue.put({"type": "done", "cancelled": True})



    def cancel_processing(self):
        if self.is_processing:
            self._cancel_event.set()
            self.cancel_button.configure(state="disabled", text="Cancelling...")
            self.log("Cancellation requested... waiting for current step to finish.")

    def go_to_review(self):
        """Navigate to review view. For batch, opens first episode."""
        session = (
            getattr(self, 'first_batch_session', None) or
            getattr(self, 'current_session', None) or
            getattr(self, 'project_session', None)
        )
        if session:
            self.on_complete_callback(session)
        else:
            import tkinter.messagebox as mb
            mb.showerror("No Session",
                         "No processed session found. Run processing first.")

    def _open_script_tool(self):
        """Navigate to Script Dashboard."""
        if hasattr(self.master, 'show_script_view'):
            self.master.show_script_view()
        else:
            import tkinter.messagebox as mb
            mb.showinfo("Script Tool",
                        "Cannot navigate — master window not found.")

