import customtkinter as ctk
import tkinter as tk
from PIL import Image, ImageTk
from core.processor import Processor

class CropWindow(ctk.CTkToplevel):
    def __init__(self, master, session, current_index, on_saved_callback):
        super().__init__(master)
        
        self.title("Manual Crop Override")
        self.geometry("1000x800")
        self.transient(master.winfo_toplevel())
        self.grab_set() # Make it modal
        
        self.session = session
        self.current_index = current_index
        self.on_saved_callback = on_saved_callback
        
        # Grid setup
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Toolbar
        self.toolbar = ctk.CTkFrame(self)
        self.toolbar.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        
        self.prev_btn = ctk.CTkButton(self.toolbar, text="< Prev", width=60, command=self.go_prev)
        self.prev_btn.pack(side="left", padx=5)
        
        self.next_btn = ctk.CTkButton(self.toolbar, text="Next >", width=60, command=self.go_next)
        self.next_btn.pack(side="left", padx=5)
        
        self.info_label = ctk.CTkLabel(self.toolbar, text="", font=ctk.CTkFont(weight="bold"))
        self.info_label.pack(side="left", padx=15)
        
        self.replace_btn = ctk.CTkButton(self.toolbar, text="Save & Replace", fg_color="red", hover_color="darkred", state="disabled", command=lambda: self.save_crop(replace=True))
        self.replace_btn.pack(side="right", padx=5)
        
        self.extract_btn = ctk.CTkButton(self.toolbar, text="Extract as New Sub-Panel", fg_color="green", hover_color="darkgreen", state="disabled", command=lambda: self.save_crop(replace=False))
        self.extract_btn.pack(side="right", padx=5)
        self.canvas_frame = ctk.CTkFrame(self)
        self.canvas_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg="gray20", cursor="cross")
        
        self.vbar = tk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.hbar = tk.Scrollbar(self.canvas_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        
        self.vbar.pack(side="right", fill="y")
        self.hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        
        # Crop variables
        self.rect_id = None
        self.start_x = 0
        self.start_y = 0
        self.end_x = 0
        self.end_y = 0
        self.scale_factor = 1.0
        
        # Bind events
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        self.load_current_image()

    def load_current_image(self):
        scenes = self.session.get_all_scenes()
        if not scenes: return
        
        self.current_index = max(0, min(self.current_index, len(scenes) - 1))
        scene = scenes[self.current_index]
        self.original_path = scene.get("original_image_path")
        self.output_path = scene.get("cleaned_image_path")
        
        self.info_label.configure(text=f"Scene {self.current_index + 1} of {len(scenes)} - Draw rectangle to crop")
        
        self.prev_btn.configure(state="normal" if self.current_index > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.current_index < len(scenes) - 1 else "disabled")
        self.replace_btn.configure(state="disabled")
        self.extract_btn.configure(state="disabled")
        
        self.canvas.delete("all")
        self.rect_id = None
        
        # Load image and scale it to fit the window without scrolling
        try:
            self.pil_img = Image.open(self.original_path)
        except Exception as e:
            self.info_label.configure(text=f"Error: Cannot open image — {e}")
            return
            
        orig_w, orig_h = self.pil_img.size
        
        # Assume max canvas size of ~950x700
        self.scale_factor = min(950 / orig_w, 700 / orig_h)
        if self.scale_factor > 1: self.scale_factor = 1.0
        
        new_w = int(orig_w * self.scale_factor)
        new_h = int(orig_h * self.scale_factor)
        
        display_img = self.pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(display_img)
        
        self.img_id = self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        self.canvas.config(scrollregion=self.canvas.bbox(self.img_id))
        
    def go_prev(self):
        self.current_index -= 1
        self.load_current_image()
        
    def go_next(self):
        self.current_index += 1
        self.load_current_image()

    def on_press(self, event):
        # Convert window coordinates to canvas coordinates
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=3, dash=(4, 4))
        self.replace_btn.configure(state="disabled")
        self.extract_btn.configure(state="disabled")

    def on_drag(self, event):
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        self.end_x = self.canvas.canvasx(event.x)
        self.end_y = self.canvas.canvasy(event.y)
        
        # Ensure coordinates are sorted
        x1, x2 = sorted([self.start_x, self.end_x])
        y1, y2 = sorted([self.start_y, self.end_y])
        
        # Ensure it's not a tiny accidental click
        if (x2 - x1) > 10 and (y2 - y1) > 10:
            self.start_x, self.end_x = x1, x2
            self.start_y, self.end_y = y1, y2
            self.replace_btn.configure(state="normal")
            self.extract_btn.configure(state="normal")
        else:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
            self.replace_btn.configure(state="disabled")
            self.extract_btn.configure(state="disabled")

    def save_crop(self, replace=True):
        orig_x1 = int(self.start_x / self.scale_factor)
        orig_y1 = int(self.start_y / self.scale_factor)
        orig_x2 = int(self.end_x / self.scale_factor)
        orig_y2 = int(self.end_y / self.scale_factor)
        crop_rect = [orig_x1, orig_y1, orig_x2, orig_y2]
        
        self.info_label.configure(text="Processing AI Text Removal... Please wait.")
        self.replace_btn.configure(state="disabled")
        self.extract_btn.configure(state="disabled")
        self.update()
        
        def run_crop():
            try:
                import time
                from core.processor import Processor
                processor = Processor()
                
                out_base = self.output_path if self.output_path else self.original_path.replace("raw_", "")
                
                # Cache buster to ensure UI updates immediately
                ts = int(time.time() * 1000)
                if replace:
                    target_output = out_base.replace(".jpg", f"_r{ts}.jpg")
                else:
                    target_output = out_base.replace(".jpg", f"_sub_{ts}.jpg")
                    
                new_data = processor.apply_manual_crop(self.original_path, target_output, crop_rect)
                
                if replace:
                    new_data["cleaned_image_path"] = target_output
                else:
                    new_data["cleaned_image_path"] = target_output
                    new_data["is_sub_panel"] = True
                    
                self.after(0, lambda: self.finish_save(new_data, replace))
            except Exception as e:
                print(f"Crop Error: {e}")
                self.after(0, lambda: self.info_label.configure(text=f"Error: {e}"))
                self.after(0, lambda: self.replace_btn.configure(state="normal"))
                self.after(0, lambda: self.extract_btn.configure(state="normal"))
                
        import threading
        threading.Thread(target=run_crop, daemon=True).start()
        
    def finish_save(self, new_data, replace):
        self.on_saved_callback(self.current_index, new_data, replace)
        scenes = self.session.get_all_scenes()
        if self.current_index < len(scenes) - 1:
            self.go_next()
        else:
            self.destroy()
