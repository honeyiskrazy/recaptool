import os
import json
import customtkinter as ctk
from tkinter import messagebox
from script_tool import CALL_1_PROMPT as DEFAULT_CALL_1
from script_tool import CALL_2_PROMPT as DEFAULT_CALL_2
from arc_merge import MERGE_PROMPT as DEFAULT_MERGE
from chapter_merge import FINAL_MERGE_PROMPT as DEFAULT_FINAL_MERGE

PROMPTS_FILE = "prompts.json"

class PromptEditorWindow(ctk.CTkToplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("Edit AI Prompts")
        self.geometry("900x700")
        self.minsize(600, 500)
        
        # Force window to stay on top of main window and grab focus
        if master:
            self.transient(master)
        self.grab_set()
        self.focus_force()
        
        # Load existing prompts
        self.prompts = self._load_prompts()
        
        # Main container
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tabs for different prompts
        self.tabview = ctk.CTkTabview(self.main_frame)
        self.tabview.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.tab_call1 = self.tabview.add("Call 1 (Story Intel)")
        self.tab_call2 = self.tabview.add("Call 2 (Script Writer)")
        self.tab_merge = self.tabview.add("Merge (Arc Stitching)")
        self.tab_final_merge = self.tabview.add("Mega Merge (Final)")
        
        # Textboxes
        self.textbox_call1 = ctk.CTkTextbox(self.tab_call1, wrap="word", font=("Consolas", 12))
        self.textbox_call1.pack(fill="both", expand=True, padx=5, pady=5)
        self.textbox_call1.insert("0.0", self.prompts.get("CALL_1_PROMPT", DEFAULT_CALL_1))
        
        self.textbox_call2 = ctk.CTkTextbox(self.tab_call2, wrap="word", font=("Consolas", 12))
        self.textbox_call2.pack(fill="both", expand=True, padx=5, pady=5)
        self.textbox_call2.insert("0.0", self.prompts.get("CALL_2_PROMPT", DEFAULT_CALL_2))
        
        self.textbox_merge = ctk.CTkTextbox(self.tab_merge, wrap="word", font=("Consolas", 12))
        self.textbox_merge.pack(fill="both", expand=True, padx=5, pady=5)
        self.textbox_merge.insert("0.0", self.prompts.get("MERGE_PROMPT", DEFAULT_MERGE))
        
        self.textbox_final_merge = ctk.CTkTextbox(self.tab_final_merge, wrap="word", font=("Consolas", 12))
        self.textbox_final_merge.pack(fill="both", expand=True, padx=5, pady=5)
        self.textbox_final_merge.insert("0.0", self.prompts.get("FINAL_MERGE_PROMPT", DEFAULT_FINAL_MERGE))
        
        # Buttons frame
        self.btn_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.btn_frame.pack(fill="x", padx=5, pady=5)
        
        self.btn_reset = ctk.CTkButton(self.btn_frame, text="Reset to Defaults", fg_color="red", hover_color="darkred", command=self._reset_defaults)
        self.btn_reset.pack(side="left", padx=5)
        
        self.btn_save = ctk.CTkButton(self.btn_frame, text="Save Prompts", fg_color="green", hover_color="darkgreen", command=self._save_prompts)
        self.btn_save.pack(side="right", padx=5)
        
    def _load_prompts(self):
        if os.path.exists(PROMPTS_FILE):
            try:
                with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARN] Failed to load prompts.json: {e}")
        return {}
        
    def _reset_defaults(self):
        if messagebox.askyesno("Reset Prompts", "Are you sure you want to restore the original hardcoded prompts?"):
            self.textbox_call1.delete("0.0", "end")
            self.textbox_call1.insert("0.0", DEFAULT_CALL_1)
            
            self.textbox_call2.delete("0.0", "end")
            self.textbox_call2.insert("0.0", DEFAULT_CALL_2)
            
            self.textbox_merge.delete("0.0", "end")
            self.textbox_merge.insert("0.0", DEFAULT_MERGE)
            
            self.textbox_final_merge.delete("0.0", "end")
            self.textbox_final_merge.insert("0.0", DEFAULT_FINAL_MERGE)
            
    def _save_prompts(self):
        data = {
            "CALL_1_PROMPT": self.textbox_call1.get("0.0", "end").strip(),
            "CALL_2_PROMPT": self.textbox_call2.get("0.0", "end").strip(),
            "MERGE_PROMPT": self.textbox_merge.get("0.0", "end").strip(),
            "FINAL_MERGE_PROMPT": self.textbox_final_merge.get("0.0", "end").strip(),
        }
        try:
            with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            messagebox.showinfo("Success", "Prompts saved successfully! The AI will use these rules from now on.")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save prompts: {e}")
