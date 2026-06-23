"""
Script Dashboard — Full Featured, New Architecture
====================================================
Folder layout:
  projects/
    {series}/
      ep_001/
        session.json
        export/
          story_intel.json    ← Call 1 output
          script.txt          ← Call 2 output
      script_merged/
        merged_script.txt     ← Merged script output
      voiceover/
        combined_voiceover.mp3

Features:
  • Series/Episode selector with ✅/⬜ status per episode
  • Per-provider API key manager (Save / Edit / Test)
  • Live stats: panels, words, cost (per provider), retries, elapsed
  • Separate error log box + main log box
  • Real-time progress bar per episode
  • Generate episode scripts (Call 1 + Call 2)
  • Merge all episode scripts into one file
  • Generate voiceover (edge-tts) with voice/rate/pitch settings
  • Load & preview generated story intel + scripts in right panel
"""

import customtkinter as ctk
import threading
import queue
import time
import os
import sys
import json
from tkinter import messagebox
from dotenv import load_dotenv, set_key
import urllib.request
import urllib.error

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECTS_DIR = os.path.join(_BASE_DIR, "projects")
_ENV_PATH = os.path.join(_BASE_DIR, ".env")

load_dotenv(_ENV_PATH)
sys.path.insert(0, _BASE_DIR)

import script_tool
import arc_merge
import chapter_merge

# Cost per 1M tokens (input, output) — rough estimates
_COST_TABLE = {
    "gemini": (0.075, 0.30),
    "groq": (0.59, 0.79),
    "openai": (0.15, 0.60),
    "anthropic": (3.00, 15.00),
    "openrouter": (0.15, 0.60),
}
_IMG_TOKENS = 258  # average tokens per image for cost estimate


# ── Stdout redirector ─────────────────────────────────────────────────────────
class _Redirector:
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text):
        if text.strip():
            self._q.put({"type": "log", "msg": text.strip()})

    def flush(self):
        pass


# ── ScriptDashboard ───────────────────────────────────────────────────────────
class ModelSelectionPopup(ctk.CTkToplevel):
    def __init__(self, master, models, call_num):
        super().__init__(master)
        self.title(f"Select Model for Call {call_num} {'(Vision Required)' if call_num == 1 else ''}")
        self.geometry("700x600")
        self.call_num = call_num
        self.models = models
        self.parent = master
        self.transient(master)

        # Top bar with Search and Filters
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=10, pady=10)
        
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.filter_models())
        ctk.CTkEntry(top_frame, textvariable=self.search_var, placeholder_text="Search models...").pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.free_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(top_frame, text="Free Only", variable=self.free_var, command=self.filter_models).pack(side="left", padx=5)
        
        self.uncensored_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(top_frame, text="Uncensored", variable=self.uncensored_var, command=self.filter_models).pack(side="left", padx=5)

        # Scrollable list
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Recommended models
        self.recommended = ["google/gemini-2.5-flash", "meta-llama/llama-3.2-11b-vision-instruct", "meta-llama/llama-3.3-70b-instruct", "anthropic/claude-3-haiku"]

        self.filter_models()

    def filter_models(self):
        for widget in self.scroll.winfo_children():
            widget.destroy()

        search_query = self.search_var.get().lower()
        free_only = self.free_var.get()
        uncensored_only = self.uncensored_var.get()

        filtered = []
        for m in self.models:
            m_id = m.get("id", "").lower()
            m_name = m.get("name", "").lower()
            
            if search_query and search_query not in m_id and search_query not in m_name:
                continue
            
            pricing = m.get("pricing", {})
            prompt_price = float(pricing.get("prompt", 0))
            is_free = prompt_price == 0
            
            if free_only and not is_free:
                continue
                
            if uncensored_only and "uncensored" not in m_id and "uncensored" not in m_name:
                continue

            # Prioritize recommended
            is_rec = m.get("id") in self.recommended
            
            arch = m.get('architecture', {})
            supports_vision = False
            if isinstance(arch, dict):
                if 'image' in str(arch.get('modality', '')).lower() or 'image' in arch.get('input_modalities', []):
                    supports_vision = True
            
            # If this is Call 1, ONLY show models that support vision
            if self.call_num == 1 and not supports_vision:
                continue

            filtered.append({
                "raw": m,
                "id": m.get("id"),
                "is_free": is_free,
                "is_rec": is_rec,
                "price": prompt_price,
                "vision": supports_vision
            })

        # Sort: Recommended first, then free, then alphabetically
        filtered.sort(key=lambda x: (not x["is_rec"], not x["is_free"], x["id"]))

        for item in filtered:
            m_id = item["id"]
            price_str = "(Free)" if item["is_free"] else f"(${item['price']*1000000:.2f}/1M)"
            vision_str = "👁️ " if item["vision"] else ""
            display_text = f"{'⭐ ' if item['is_rec'] else ''}{vision_str}{m_id} {price_str}"
            
            btn = ctk.CTkButton(
                self.scroll, 
                text=display_text, 
                anchor="w", 
                fg_color="transparent", 
                text_color="#00ff00" if item["is_free"] else "white",
                hover_color="#333333",
                command=lambda raw_id=m_id, vis=item["vision"]: self.select_model(raw_id, vis)
            )
            btn.pack(fill="x", pady=2)

    def select_model(self, model_id, supports_vision):
        import tkinter.messagebox as messagebox
        if self.call_num == 1 and not supports_vision:
            messagebox.showerror("Vision Required", f"{model_id} does not support image inputs!\nCall 1 requires a vision-capable model to analyze panels.")
            return

        from dotenv import set_key
        if self.call_num == 1:
            self.parent._model1_var.set(model_id)
            os.environ["OPENROUTER_MODEL_CALL_1"] = model_id
            set_key(self.parent._env_path, "OPENROUTER_MODEL_CALL_1", model_id)
        else:
            self.parent._model2_var.set(model_id)
            os.environ["OPENROUTER_MODEL_CALL_2"] = model_id
            set_key(self.parent._env_path, "OPENROUTER_MODEL_CALL_2", model_id)
        
        self.destroy()



class ScriptDashboard(ctk.CTkFrame):

    def __init__(self, master, on_back_callback=None):
        super().__init__(master)
        self.on_back_callback = on_back_callback or (lambda: None)

        self._q = queue.Queue()
        self._cancel = threading.Event()
        self._is_processing = False
        self._start_time = 0
        self._original_stdout = sys.stdout
        self._env_path = os.path.join(os.getcwd(), ".env")

        # running counters
        self._total_panels = 0
        self._total_words = 0
        self._total_retries = 0
        self._total_cost = 0.0

        # voiceover
        self._vo_voice = "en-US-ChristopherNeural"
        self._vo_rate = "+0%"
        self._vo_pitch = "+0Hz"

        # 3-column layout (Left 25%, Center 25%, Right 50%)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self._build_left()
        self._build_middle()
        self._build_right()

        self._refresh_series()
        self.after(100, self._tick)
        self._check_api_balance()

    def _check_api_balance(self):
        if not hasattr(self, "_bal_label") or not self._bal_label.winfo_exists():
            return
        self._bal_label.configure(text="API Balance: Checking...", text_color="gray")
        def _fetch():
            import requests, os
            key = os.getenv("OPENROUTER_API_KEY")
            if not key:
                if self._bal_label.winfo_exists():
                    self.after(0, lambda: self._bal_label.configure(text="API Balance: No Key Set", text_color="red"))
                return
            try:
                resp = requests.get(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    limit = data.get("limit")
                    rem = data.get("limit_remaining")
                    is_free = data.get("is_free_tier", False)
                    if self._bal_label.winfo_exists():
                        if is_free:
                            self.after(0, lambda: self._bal_label.configure(text="API Balance: Free Tier", text_color="#b8860b"))
                        elif rem is not None:
                            self.after(0, lambda r=rem: self._bal_label.configure(text=f"API Balance: ${r:.2f}", text_color="#2FA572"))
                        elif limit is None:
                            self.after(0, lambda: self._bal_label.configure(text="API Balance: Unlimited", text_color="#2FA572"))
                        else:
                            self.after(0, lambda: self._bal_label.configure(text="API Balance: Unknown", text_color="orange"))
                else:
                    if self._bal_label.winfo_exists():
                        self.after(0, lambda: self._bal_label.configure(text="API Balance: Auth Error", text_color="red"))
            except Exception:
                if self._bal_label.winfo_exists():
                    self.after(0, lambda: self._bal_label.configure(text="API Balance: Offline", text_color="red"))
        
        threading.Thread(target=_fetch, daemon=True).start()

    # =========================================================================
    # LEFT PANEL — controls, series/episode selector, API keys
    # =========================================================================
    def _build_left(self):
        lf = ctk.CTkScrollableFrame(self)
        lf.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._lf = lf

        ctk.CTkLabel(
            lf, text="Script Generator", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(fill="x", padx=10, pady=(12, 4))

        ctk.CTkButton(
            lf,
            text="← Back to Home",
            fg_color="gray",
            hover_color="darkgray",
            command=self.on_back_callback,
        ).pack(fill="x", padx=10, pady=(0, 10))

        # ── API Balance Check ────────────────────────────────────────────────
        bal_row = ctk.CTkFrame(lf, fg_color="transparent")
        bal_row.pack(fill="x", padx=10, pady=(0, 10))
        
        self._bal_label = ctk.CTkLabel(bal_row, text="API Balance: Checking...", font=ctk.CTkFont(weight="bold"), text_color="#2FA572")
        self._bal_label.pack(side="left")
        
        ctk.CTkButton(
            bal_row,
            text="↻",
            width=30,
            height=24,
            fg_color="transparent",
            border_width=1,
            text_color=("black", "white"),
            command=self._check_api_balance
        ).pack(side="right")

        # ── Model Selection (OpenRouter) ──────────────────────────────────────
        model_row = ctk.CTkFrame(lf, fg_color="transparent")
        model_row.pack(fill="x", padx=10, pady=(2, 10))

        ctk.CTkLabel(model_row, text="Vision Model:").grid(row=0, column=0, sticky="w", pady=2)
        self._model1_var = ctk.StringVar(value=os.getenv("OPENROUTER_MODEL_CALL_1", "Select Vision Model"))
        self._model1_btn = ctk.CTkButton(
            model_row,
            textvariable=self._model1_var,
            width=220,
            command=lambda: self._open_model_popup(1)
        )
        self._model1_btn.grid(row=0, column=1, padx=(10, 0), pady=2)

        ctk.CTkLabel(model_row, text="Script Model:").grid(row=1, column=0, sticky="w", pady=2)
        self._model2_var = ctk.StringVar(value=os.getenv("OPENROUTER_MODEL_CALL_2", "Select Script Model"))
        self._model2_btn = ctk.CTkButton(
            model_row,
            textvariable=self._model2_var,
            width=220,
            command=lambda: self._open_model_popup(2)
        )
        self._model2_btn.grid(row=1, column=1, padx=(10, 0), pady=2)

        self._fetched_models = []
        self._raw_models_dict = {}
        
        self._model1_var.trace_add("write", self._update_pre_cost)
        self._model2_var.trace_add("write", self._update_pre_cost)
        
        threading.Thread(target=self._fetch_openrouter_models, daemon=True).start()

        # ── Series selector ───────────────────────────────────────────────────
        ctk.CTkLabel(lf, text="Series:").pack(anchor="w", padx=10)
        self._series_var = ctk.StringVar(value="")
        self._series_menu = ctk.CTkOptionMenu(
            lf,
            variable=self._series_var,
            values=["(refresh)"],
            command=self._on_series_change,
        )
        self._series_menu.pack(fill="x", padx=10, pady=(2, 2))

        ref_row = ctk.CTkFrame(lf, fg_color="transparent")
        ref_row.pack(fill="x", padx=10, pady=(2, 6))
        ctk.CTkButton(
            ref_row, text="⟳ Refresh Series", width=130, command=self._refresh_series
        ).pack(side="left")

        # ── Episode list ──────────────────────────────────────────────────────
        ctk.CTkLabel(lf, text="Episodes:").pack(anchor="w", padx=10)
        self._ep_scroll = ctk.CTkScrollableFrame(lf, height=200)
        self._ep_scroll.pack(fill="x", padx=10, pady=(2, 8))
        self._ep_vars: dict[str, ctk.BooleanVar] = {}

        # ── Action buttons ────────────────────────────────────────────────────
        self._gen_btn = ctk.CTkButton(
            lf,
            text="▶  Generate Story Intel (Call 1)",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            command=self._start_generation,
        )
        self._gen_btn.pack(fill="x", padx=10, pady=(4, 2))

        self._script_btn = ctk.CTkButton(
            lf,
            text="✍  Generate Scripts (Call 2)",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#0066cc",
            hover_color="#004d99",
            command=self._start_scripts,
        )
        self._script_btn.pack(fill="x", padx=10, pady=2)

        self._merge_btn = ctk.CTkButton(
            lf,
            text="🔗  Merge Scripts",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#5A4EA3",
            hover_color="#3D3575",
            command=self._start_merge,
        )
        self._merge_btn.pack(fill="x", padx=10, pady=2)

        self._mega_merge_btn = ctk.CTkButton(
            lf,
            text="🌟  Mega Merge (10-Ep Chunks)",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#8E44AD",
            hover_color="#5B2C6F",
            command=self._start_mega_merge,
        )
        self._mega_merge_btn.pack(fill="x", padx=10, pady=2)

        vo_row = ctk.CTkFrame(lf, fg_color="transparent")
        vo_row.pack(fill="x", padx=10, pady=2)
        self._vo_btn = ctk.CTkButton(
            vo_row,
            text="🎙  Generate Voiceover",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2FA572",
            hover_color="#106A43",
            command=self._start_voiceover,
        )
        self._vo_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            vo_row,
            text="⚙️",
            width=40,
            height=40,
            fg_color="gray",
            hover_color="darkgray",
            command=self._open_vo_settings,
        ).pack(side="right")

        self._cancel_btn = ctk.CTkButton(
            lf,
            text="✖  Cancel API",
            height=30,
            font=ctk.CTkFont(weight="bold"),
            fg_color="red",
            hover_color="darkred",
            state="disabled",
            command=self._cancel_processing,
        )
        self._cancel_btn.pack(fill="x", padx=10, pady=(2, 2))
        
        self._reset_ui_btn = ctk.CTkButton(
            lf,
            text="🔄  Force Reset UI",
            height=30,
            font=ctk.CTkFont(weight="bold"),
            fg_color="orange",
            hover_color="darkorange",
            command=self._force_reset_ui,
        )
        self._reset_ui_btn.pack(fill="x", padx=10, pady=(2, 12))

        # ── Edit Prompts ──────────────────────────────────────────────────────
        self._prompts_btn = ctk.CTkButton(
            lf,
            text="📝  Edit AI Prompts",
            height=30,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#0052cc",
            hover_color="#003d99",
            command=self._open_prompt_editor,
        )
        self._prompts_btn.pack(fill="x", padx=10, pady=(2, 12))

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkLabel(lf, text="─" * 40, text_color="gray").pack(fill="x", padx=10)

        # ── API Key Manager ───────────────────────────────────────────────────
        ctk.CTkLabel(
            lf, text="API Key Manager", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 4))

        self._api_entries: dict[str, ctk.CTkEntry] = {}
        self._api_btns: dict[str, ctk.CTkButton] = {}

        for prov in ["openrouter"]:
            row = ctk.CTkFrame(lf, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=3)

            ctk.CTkLabel(row, text=prov.title(), width=76, anchor="w").pack(side="left")

            ent = ctk.CTkEntry(
                row, placeholder_text=f"{prov.title()} API key", show="*"
            )
            ent.pack(side="left", fill="x", expand=True, padx=4)

            save_btn = ctk.CTkButton(
                row,
                text="Save",
                width=48,
                command=lambda p=prov, e=ent: self._save_key(p, e),
            )
            save_btn.pack(side="left", padx=2)

            test_btn = ctk.CTkButton(
                row, text="Test", width=48, command=lambda p=prov: self._test_key(p)
            )
            test_btn.pack(side="right", padx=2)

            self._api_entries[prov] = ent
            self._api_btns[prov] = save_btn

            existing = os.getenv(f"{prov.upper()}_API_KEY", "")
            if existing:
                ent.configure(show="")
                ent.insert(0, "••••••••••••••••")
                ent.configure(state="disabled")
                save_btn.configure(
                    text="Edit",
                    fg_color="gray",
                    command=lambda p=prov, e=ent, b=save_btn: self._toggle_key(p, e, b),
                )

    # =========================================================================
    # MIDDLE PANEL — Live Command Center
    # =========================================================================
    def _build_middle(self):
        mf = ctk.CTkFrame(self)
        mf.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        mf.grid_rowconfigure(2, weight=1)
        mf.grid_rowconfigure(4, weight=2)
        mf.grid_columnconfigure(0, weight=1)

        # ── Stats block ───────────────────────────────────────────────────────
        stats = ctk.CTkFrame(mf)
        stats.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        stats.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(
            stats, text="LIVE COMMAND CENTER", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, columnspan=4, pady=(12, 18))

        def _s(r, c, label, attr, color=None):
            ctk.CTkLabel(stats, text=label, font=ctk.CTkFont(weight="bold")).grid(
                row=r, column=c, sticky="e", padx=6
            )
            kw = {"text_color": color} if color else {}
            lbl = ctk.CTkLabel(stats, text="—", **kw)
            lbl.grid(row=r, column=c + 1, sticky="w", padx=6)
            setattr(self, attr, lbl)

        _s(1, 0, "Current Phase:", "_stat_phase", "#00ff00")
        _s(1, 2, "Time Elapsed:", "_stat_time")
        _s(2, 0, "Total Panels:", "_stat_panels")
        _s(2, 2, "API Retries:", "_stat_retries", "orange")
        _s(3, 0, "Script Words:", "_stat_words")
        _s(3, 2, "Est. Cost:", "_stat_cost", "#00ff00")

        _s(4, 0, "", "_stat_blank")
        _s(4, 2, "Est. Total Cost (Expected):", "_stat_precost", "yellow")

        self._prog = ctk.CTkProgressBar(stats)
        self._prog.grid(
            row=5, column=0, columnspan=4, padx=20, pady=(18, 12), sticky="ew"
        )
        self._prog.set(0)

        # ── Episode status ────────────────────────────────────────────────────
        self._ep_status_label = ctk.CTkLabel(
            stats, text="", font=ctk.CTkFont(size=12), text_color="#aaaaaa"
        )
        self._ep_status_label.grid(row=6, column=0, columnspan=4, pady=(0, 10))

        # ── Error Alerts ──────────────────────────────────────────────────────
        ctk.CTkLabel(
            mf,
            text="⚠ Error Alerts & Retries:",
            font=ctk.CTkFont(weight="bold"),
            text_color="red",
        ).grid(row=1, column=0, sticky="sw", padx=10)

        self._err_box = ctk.CTkTextbox(
            mf,
            state="disabled",
            font=("Consolas", 12),
            text_color="#ff4444",
            height=100,
        )
        self._err_box.grid(row=2, column=0, padx=10, pady=(0, 6), sticky="nsew")

        # ── Terminal Log ──────────────────────────────────────────────────────
        ctk.CTkLabel(
            mf, text="Standard Terminal Logs:", font=ctk.CTkFont(weight="bold")
        ).grid(row=3, column=0, sticky="sw", padx=10)

        self._log_box = ctk.CTkTextbox(mf, state="disabled", font=("Consolas", 12))
        self._log_box.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="nsew")

    # =========================================================================
    # RIGHT PANEL — Output Review
    # =========================================================================
    def _build_right(self):
        rf = ctk.CTkFrame(self)
        rf.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
        rf.grid_rowconfigure(2, weight=1)
        rf.grid_rowconfigure(4, weight=5)
        rf.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(rf, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text="Output Review", font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            hdr,
            text="📂 Load Saved Script",
            width=150,
            fg_color="gray",
            hover_color="darkgray",
            command=self._load_saved_script,
        ).grid(row=0, column=1, sticky="e")

        intel_hdr = ctk.CTkFrame(rf, fg_color="transparent")
        intel_hdr.grid(row=1, column=0, sticky="ew", padx=10)
        intel_hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(intel_hdr, text="Input Data Preview (Story Intel):").grid(row=0, column=0, sticky="sw")
        self._save_intel_btn = ctk.CTkButton(
            intel_hdr, text="💾 Save Edits", width=100, state="disabled", fg_color="gray", hover_color="#106A43", command=self._save_intel_edits
        )
        self._save_intel_btn.grid(row=0, column=1, sticky="se")

        self._intel_box = ctk.CTkTextbox(rf, state="normal")
        self._intel_box.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="nsew")
        self._intel_box.bind("<KeyRelease>", self._check_intel_edits)

        ctk.CTkLabel(rf, text="Final Script Output:").grid(
            row=3, column=0, sticky="sw", padx=10
        )
        self._script_box = ctk.CTkTextbox(
            rf, state="disabled", font=("Helvetica", 18, "bold")
        )
        self._script_box.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="nsew")

    # =========================================================================
    # Series / Episode helpers
    # =========================================================================
    def _get_series(self) -> list[str]:
        if not os.path.exists(_PROJECTS_DIR):
            return []
        result = []
        for d in sorted(os.listdir(_PROJECTS_DIR)):
            sp = os.path.join(_PROJECTS_DIR, d)
            if not os.path.isdir(sp):
                continue
            eps = [
                e
                for e in os.listdir(sp)
                if e.startswith("ep_")
                and os.path.exists(os.path.join(sp, e, "session.json"))
            ]
            if eps:
                result.append(d)
        return result

    def _get_episodes(self, series: str) -> list[str]:
        sp = os.path.join(_PROJECTS_DIR, series)
        if not os.path.exists(sp):
            return []
        return sorted(
            [
                e
                for e in os.listdir(sp)
                if e.startswith("ep_")
                and os.path.exists(os.path.join(sp, e, "session.json"))
            ]
        )

    def _refresh_series(self):
        series = self._get_series()
        if not series:
            self._series_menu.configure(values=["(no series found)"])
            self._series_var.set("(no series found)")
            return

        opts = ["Select Series..."] + series
        self._series_menu.configure(values=opts)

        if self._series_var.get() not in series:
            self._series_var.set("Select Series...")

        self._on_series_change(self._series_var.get())

    def _on_series_change(self, series: str):
        for w in self._ep_scroll.winfo_children():
            w.destroy()
        self._ep_vars.clear()

        if not series or series == "Select Series..." or series.startswith("("):
            return

        episodes = self._get_episodes(series)
        if not episodes:
            ctk.CTkLabel(self._ep_scroll, text="No episodes found").pack(pady=10)
            return

        # Select All / None / Pending row
        sr = ctk.CTkFrame(self._ep_scroll, fg_color="transparent")
        sr.pack(fill="x", pady=(0, 4))
        ctk.CTkButton(
            sr, text="All", width=50, command=lambda: self._sel_all(True)
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            sr, text="None", width=50, command=lambda: self._sel_all(False)
        ).pack(side="left", padx=2)
        ctk.CTkButton(sr, text="Pending", width=70, command=self._sel_pending).pack(
            side="left", padx=2
        )

        for ep in episodes:
            done = os.path.exists(
                os.path.join(_PROJECTS_DIR, series, ep, "export", "script.txt")
            )
            var = ctk.BooleanVar(value=not done)
            var.trace_add("write", self._update_pre_cost)
            
            row = ctk.CTkFrame(self._ep_scroll, fg_color="transparent")
            row.pack(fill="x", padx=2, pady=2)
            
            cb = ctk.CTkCheckBox(row, text="", variable=var, width=24)
            cb.pack(side="left")
            
            btn = ctk.CTkButton(
                row, 
                text=f"{'✅' if done else '⬜'} {ep}", 
                fg_color="transparent", 
                text_color=("black", "white"),
                anchor="w",
                hover_color=("gray75", "gray25"),
                command=lambda e=ep: self._view_episode_results(series, e)
            )
            btn.pack(side="left", fill="x", expand=True)
            
            self._ep_vars[ep] = var

        self._update_pre_cost()

    def _view_episode_results(self, series: str, ep: str):
        self._current_view_series = series
        self._current_view_ep = ep
        if hasattr(self, '_save_intel_btn'):
            self._save_intel_btn.configure(state="disabled", fg_color="gray")
            
        self._intel_box.configure(state="normal")
        self._script_box.configure(state="normal")
        
        self._intel_box.delete("1.0", "end")
        self._script_box.delete("1.0", "end")
        
        intel_path = os.path.join(_PROJECTS_DIR, series, ep, "export", "story_intel.json")
        script_path = os.path.join(_PROJECTS_DIR, series, ep, "export", "script.txt")
        
        if os.path.exists(intel_path):
            with open(intel_path, "r", encoding="utf-8") as f:
                content = f.read()
                self._intel_box.insert("end", content)
                self._current_intel_original_text = content
        else:
            msg = f"No story intel found for {ep}"
            self._intel_box.insert("end", msg)
            self._current_intel_original_text = msg
            
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                self._script_box.insert("end", f.read())
        else:
            self._script_box.insert("end", f"No script found for {ep}")
            
        self._script_box.configure(state="disabled")

    def _check_intel_edits(self, event=None):
        if not hasattr(self, '_current_intel_original_text'): return
        current_text = self._intel_box.get("1.0", "end-1c")
        if current_text != self._current_intel_original_text:
            self._save_intel_btn.configure(state="normal", fg_color="#2FA572")
        else:
            self._save_intel_btn.configure(state="disabled", fg_color="gray")

    def _save_intel_edits(self):
        if not hasattr(self, '_current_view_series') or not hasattr(self, '_current_view_ep'): return
        current_text = self._intel_box.get("1.0", "end-1c")
        
        try:
            json.loads(current_text)
        except Exception as e:
            import tkinter.messagebox as messagebox
            messagebox.showerror("JSON Error", f"Cannot save: Invalid JSON format.\n\n{e}")
            return
            
        intel_path = os.path.join(_PROJECTS_DIR, self._current_view_series, self._current_view_ep, "export", "story_intel.json")
        with open(intel_path, "w", encoding="utf-8") as f:
            f.write(current_text)
            
        self._current_intel_original_text = current_text
        self._save_intel_btn.configure(state="disabled", fg_color="gray")
        print(f"  ✅ Saved manual edits to story_intel.json for {self._current_view_ep}")

    def _sel_all(self, v: bool):
        for var in self._ep_vars.values():
            var.set(v)

    def _sel_pending(self):
        s = self._series_var.get()
        for ep, var in self._ep_vars.items():
            done = os.path.exists(
                os.path.join(_PROJECTS_DIR, s, ep, "export", "script.txt")
            )
            var.set(not done)

    def _selected_eps(self) -> list[str]:
        return [ep for ep, v in self._ep_vars.items() if v.get()]

    # =========================================================================
    # Generation (Call 1 + Call 2 per episode)
    # =========================================================================

    def _fetch_openrouter_models(self):
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/models")
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                
            models = data.get("data", [])
            self._fetched_models = models
            print("[API] Successfully fetched OpenRouter models.")
        except Exception as e:
            print(f"[API] Error fetching models: {e}")

    def _open_model_popup(self, call_num):
        if not hasattr(self, '_fetched_models') or not self._fetched_models:
            import tkinter.messagebox as messagebox
            messagebox.showinfo("Loading", "Models are still loading from OpenRouter. Please wait a moment.")
            return
        
        popup = ModelSelectionPopup(self, self._fetched_models, call_num)
        popup.grab_set()

    def _update_pre_cost(self, *args):
        if not hasattr(self, '_fetched_models') or not hasattr(self, '_stat_precost'): return
        
        m1_raw = self._model1_var.get()
        m2_raw = self._model2_var.get()
        in_c1, out_c1 = 0.0, 0.0
        in_c2, out_c2 = 0.0, 0.0
        
        for m in self._fetched_models:
            if m['id'] == m1_raw:
                p = m.get('pricing', {})
                in_c1, out_c1 = float(p.get('prompt', 0)), float(p.get('completion', 0))
            if m['id'] == m2_raw:
                p = m.get('pricing', {})
                in_c2, out_c2 = float(p.get('prompt', 0)), float(p.get('completion', 0))
                
        series = self._series_var.get()
        if not series or series.startswith("("):
            self._stat_precost.configure(text="$0.0000")
            return
            
        episodes = self._selected_eps()
        total_panels = 0
        for ep in episodes:
            session_path = os.path.join(_PROJECTS_DIR, series, ep, "session.json")
            if os.path.exists(session_path):
                try:
                    with open(session_path, "r", encoding="utf-8") as f:
                        sess = json.load(f)
                        total_panels += len(sess)
                except: pass
                
        # Call 1 Input = Images (258 tokens each) + OCR text (~150 tokens per panel)
        # Call 1 Output = JSON (~60 tokens per panel)
        c1_est_cost = (total_panels * (258 + 150) * in_c1) + (total_panels * 60 * out_c1)
        
        # Call 2 Input = JSON Intel (~100 tokens per panel)
        # Call 2 Output = Script Narration (~30 tokens per panel)
        c2_est_cost = (total_panels * 100 * in_c2) + (total_panels * 30 * out_c2)
        
        cost = c1_est_cost + c2_est_cost
        self._stat_precost.configure(text=f"${cost:.4f}")

        # Dynamic Button Enabling
        has_intel = False
        has_script = False
        for ep in episodes:
            intel_path = os.path.join(_PROJECTS_DIR, series, ep, "export", "story_intel.json")
            script_path = os.path.join(_PROJECTS_DIR, series, ep, "export", "script.txt")
            if os.path.exists(intel_path): has_intel = True
            if os.path.exists(script_path): has_script = True
            
        if episodes and has_intel:
            self._script_btn.configure(state="normal")
        else:
            self._script_btn.configure(state="disabled")
            
        if episodes and has_script:
            self._merge_btn.configure(state="normal")
            self._mega_merge_btn.configure(state="normal")
        else:
            self._merge_btn.configure(state="disabled")
            self._mega_merge_btn.configure(state="disabled")

    def _start_generation(self):
        if self._is_processing:
            return
        series = self._series_var.get()
        episodes = self._selected_eps()
        if not series or series.startswith("("):
            messagebox.showerror("No Series", "Select a series first.")
            return
        if not episodes:
            messagebox.showerror("No Episodes", "Check at least one series checkbox.")
            return

        self._set_processing(True)
        self._reset_stats()
        self._clear_logs()
        sys.stdout = _Redirector(self._q)

        m1 = self._model1_var.get()
        m2 = self._model2_var.get()
        threading.Thread(target=self._run_generation, args=(series, episodes, m1, m2), daemon=True).start()

    def _run_generation(self, series: str, episodes: list[str], model1_raw: str, model2_raw: str):
        total = len(episodes)
        self._total_panels = 0
        self._total_words = 0
        self._total_cost = 0.0
        
        os.environ["OPENROUTER_MODEL_CALL_1"] = model1_raw
        set_key(self._env_path, "OPENROUTER_MODEL_CALL_1", model1_raw)
        
        os.environ["OPENROUTER_MODEL_CALL_2"] = model2_raw
        set_key(self._env_path, "OPENROUTER_MODEL_CALL_2", model2_raw)

        in_c1, out_c1 = 0.0, 0.0
        in_c2, out_c2 = 0.0, 0.0
        if hasattr(self, '_fetched_models'):
            for m in self._fetched_models:
                if m['id'] == model1_raw:
                    p = m.get('pricing', {})
                    in_c1, out_c1 = float(p.get('prompt', 0)), float(p.get('completion', 0))
                if m['id'] == model2_raw:
                    p = m.get('pricing', {})
                    in_c2, out_c2 = float(p.get('prompt', 0)), float(p.get('completion', 0))

        print(f"[START] Processing {total} episodes…")

        intel_path = None
        script_path = None

        try:
            for i, ep in enumerate(episodes):
                if self._cancel.is_set():
                    raise RuntimeError("Cancelled by user")

                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        if self._cancel.is_set():
                            raise RuntimeError("Cancelled by user")

                        self._q.put(
                            {"type": "ep_status", "msg": f"Episode {i+1}/{total}: {ep} (Attempt {attempt+1}/{max_retries})"}
                        )
                        self._q.put({"type": "progress_base", "val": i / total})

                        print(f"\n{'═'*42}")
                        print(f"[CHUNK] Episode {i+1}/{total}: {ep} (Attempt {attempt+1})")
                        print(f"{'═'*42}")

                        ep_dir = os.path.join(_PROJECTS_DIR, series, ep)
                        session_path = os.path.join(ep_dir, "session.json")
                        export_dir = os.path.join(ep_dir, "export")
                        os.makedirs(export_dir, exist_ok=True)

                        intel_path = os.path.join(export_dir, "story_intel.json")
                        script_path = os.path.join(export_dir, "script.txt")

                        if os.path.exists(intel_path):
                            print("  ⏭  Story Intel already exists. Skipping.")
                            break

                        # Load session
                        print("[CHUNK] Loading session panels…")
                        panels = script_tool.preprocess_session(session_path)
                        if not panels:
                            print(f"[ERROR] No panels found in {ep}. Skipping.")
                            break

                        # Encode images
                        print(f"[CHUNK] Encoding {len(panels)} panels for AI…")
                        encoded = script_tool.encode_images(panels)
                        self._total_panels += len(encoded)
                        print(f"[STATS] total_panels={self._total_panels}")

                        with open(session_path, "r", encoding="utf-8") as f:
                            sess = json.load(f)
                        source_url = sess[0].get("source_url", "") if sess else ""

                        full_ocr_texts = []
                        for p in sess:
                            if p.get("ocr_text"):
                                txt = " ".join(p["ocr_text"]) if isinstance(p["ocr_text"], list) else str(p["ocr_text"])
                                full_ocr_texts.append(f"Scene {p.get('scene_id', p.get('index', '?'))}: {txt}")
                        full_ocr_text_str = "\n".join(full_ocr_texts)

                        pm = script_tool.ProviderManager()
                        
                        def _prog_cb(msg, frac=0.0):
                            print(f"[CHUNK] {msg}")
                            self._q.put({"type": "progress_base", "val": (i + frac) / total})
                            
                        def _usage_c1(in_tok, out_tok, text):
                            self._total_cost += (in_tok * in_c1) + (out_tok * out_c1)
                            print(f"[STATS] cost={self._total_cost:.5f}")
                            
                        def _usage_c2(in_tok, out_tok, text):
                            w = len(text.split()) if text else 0
                            self._total_words += w
                            self._total_cost += (in_tok * in_c2) + (out_tok * out_c2)
                            print(f"[STATS] words={self._total_words}")
                            print(f"[STATS] cost={self._total_cost:.5f}")

                        # Call 1
                        print("[CHUNK] Call 1 — Story Intelligence…")
                        story_intel = pm.execute_call_1(encoded, source_url, full_ocr_text_str, progress_callback=_prog_cb, usage_callback=_usage_c1)

                        if self._cancel.is_set():
                            raise RuntimeError("Cancelled by user")

                        with open(intel_path, "w", encoding="utf-8") as f:
                            json.dump(story_intel, f, indent=2, ensure_ascii=False)
                        print("  ✅ Story intel saved.")
                        break  # Success! Break out of retry loop

                    except Exception as loop_e:
                        if str(loop_e) == "Cancelled by user":
                            raise loop_e
                        print(f"\n[ERROR] Episode {ep} failed on attempt {attempt+1}: {loop_e}")
                        import traceback
                        traceback.print_exc(file=sys.stdout)
                        if attempt < max_retries - 1:
                            print(f"  ↻ Retrying {ep} in 5 seconds...")
                            import time
                            time.sleep(5)
                        else:
                            print(f"  ❌ Skipping {ep} completely after {max_retries} failed attempts.")

            self._q.put({"type": "progress_base", "val": 1.0})
            self._q.put(
                {
                    "type": "done",
                    "intel_path": intel_path,
                }
            )

        except Exception as e:
            import traceback

            if str(e) == "Cancelled by user":
                print("\n[INFO] Process cancelled by user.")
            else:
                print(f"[ERROR] {e}")
                traceback.print_exc(file=sys.stdout)
            self._q.put({"type": "error"})
        finally:
            sys.stdout = self._original_stdout

    # =========================================================================
    # Merge episode scripts
    # =========================================================================
    def _start_scripts(self):
        if self._is_processing:
            return
        series = self._series_var.get()
        if not series or series.startswith("("):
            messagebox.showerror("No Series", "Select a series first.")
            return
        self._set_processing(True)
        self._reset_stats()
        self._clear_logs()
        sys.stdout = _Redirector(self._q)
        provider2 = self._model2_var.get()

        threading.Thread(
            target=self._run_scripts, args=(series, provider2), daemon=True
        ).start()

    def _run_scripts(self, series: str, provider: str):
        try:
            os.environ["OPENROUTER_MODEL_CALL_2"] = provider
            set_key(self._env_path, "OPENROUTER_MODEL_CALL_2", provider)

            in_c2, out_c2 = 0.0, 0.0
            if hasattr(self, '_fetched_models'):
                for m in self._fetched_models:
                    if m['id'] == provider:
                        p = m.get('pricing', {})
                        in_c2, out_c2 = float(p.get('prompt', 0)), float(p.get('completion', 0))

            pm = script_tool.ProviderManager()
            
            def _prog_cb(msg, frac=0.0):
                print(f"[CHUNK] {msg}")
                if hasattr(self, '_current_merge_i') and hasattr(self, '_current_merge_total'):
                    i_val = getattr(self, '_current_merge_i')
                    tot_val = getattr(self, '_current_merge_total')
                    self._q.put({"type": "progress_base", "val": (i_val + frac) / tot_val})
                
            def _usage_c2(in_tok, out_tok, text):
                w = len(text.split()) if text else 0
                self._total_words += w
                self._total_cost += (in_tok * in_c2) + (out_tok * out_c2)
                print(f"[STATS] words={self._total_words}")
                print(f"[STATS] cost={self._total_cost:.5f}")

            episodes = self._get_episodes(series)
            paths = []

            self._current_merge_total = len(episodes)
            for i, ep in enumerate(episodes):
                self._current_merge_i = i
                if self._cancel.is_set():
                    raise RuntimeError("Cancelled by user")

                self._q.put({"type": "ep_status", "msg": f"Episode {i+1}/{len(episodes)}: {ep}"})

                sp = os.path.join(_PROJECTS_DIR, series, ep, "export", "script.txt")
                ip = os.path.join(_PROJECTS_DIR, series, ep, "export", "story_intel.json")
                
                if not os.path.exists(sp):
                    if os.path.exists(ip):
                        print(f"\n{'═'*42}")
                        print(f"[CHUNK] Episode {i+1}/{len(episodes)}: {ep} — Call 2")
                        print(f"{'═'*42}")
                        
                        max_retries = 3
                        success = False
                        for attempt in range(max_retries):
                            try:
                                with open(ip, "r", encoding="utf-8") as f:
                                    story_intel = json.load(f)
                                    
                                paragraphs = pm.execute_call_2(story_intel, progress_callback=_prog_cb, usage_callback=_usage_c2)

                                if self._cancel.is_set():
                                    raise RuntimeError("Cancelled by user")

                                para_path = os.path.join(os.path.dirname(sp), "script_paragraphs.json")
                                with open(para_path, "w", encoding="utf-8") as f:
                                    json.dump(paragraphs, f, indent=2, ensure_ascii=False)

                                plain_text = "\n\n".join(p["paragraph"] for p in paragraphs if p.get("paragraph"))
                                with open(sp, "w", encoding="utf-8") as f:
                                    f.write(plain_text)

                                print(f"  ✅ {len(plain_text.split())} words, {len(paragraphs)} paragraphs → {sp}")
                                paths.append(sp)
                                success = True
                                break
                            except Exception as loop_e:
                                if str(loop_e) == "Cancelled by user":
                                    raise loop_e
                                print(f"\n[ERROR] Episode {ep} Call 2 failed on attempt {attempt+1}: {loop_e}")
                                import traceback
                                traceback.print_exc(file=sys.stdout)
                                if attempt < max_retries - 1:
                                    print(f"  ↻ Retrying {ep} in 5 seconds...")
                                    import time
                                    time.sleep(5)
                                else:
                                    print(f"  ❌ Skipping {ep} completely after {max_retries} failed attempts.")
                                    
                        if not success:
                            continue
                    else:
                        print(f"[ERROR] Missing story intel for {ep}. Run Call 1 first.")
                else:
                    paths.append(sp)
                    print(f"[INFO] Script already exists for {ep}, skipping generation.")

            if not paths:
                raise ValueError("No episode scripts generated.")

            self._q.put({"type": "progress_base", "val": 1.0})
            
            # Show the last generated script in the UI
            with open(paths[-1], "r", encoding="utf-8") as f:
                last_script = f.read()
                
            self._q.put({
                "type": "done",
                "script_path": paths[-1],
                "script_content": last_script,
            })

        except Exception as e:
            import traceback

            if str(e) == "Cancelled by user":
                print("\n[INFO] Process cancelled by user.")
            else:
                print(f"[ERROR] {e}")
                traceback.print_exc(file=sys.stdout)
            self._q.put({"type": "error"})
        finally:
            sys.stdout = self._original_stdout

    def _start_merge(self):
        if self._is_processing:
            return
        series = self._series_var.get()
        if not series or series.startswith("("):
            messagebox.showerror("No Series", "Select a series first.")
            return
        self._set_processing(True)
        self._reset_stats()
        self._clear_logs()
        sys.stdout = _Redirector(self._q)
        provider2 = self._model2_var.get()

        threading.Thread(
            target=self._run_merge, args=(series, provider2), daemon=True
        ).start()

    def _run_merge(self, series: str, provider: str):
        try:
            os.environ["OPENROUTER_MODEL_CALL_2"] = provider
            set_key(self._env_path, "OPENROUTER_MODEL_CALL_2", provider)

            episodes = self._get_episodes(series)
            paths = []
            
            for ep in episodes:
                sp = os.path.join(_PROJECTS_DIR, series, ep, "export", "script.txt")
                if os.path.exists(sp):
                    paths.append(sp)
                else:
                    print(f"[WARN] Missing script for {ep}, it will be excluded from the merge.")
            
            if not paths:
                raise ValueError("No episode scripts found. Run 'Generate Scripts (Call 2)' first.")

            print(f"\n[CHUNK] Merging {len(paths)} episode scripts…")
            self._q.put({"type": "progress_base", "val": 0.5})
            
            out_path = arc_merge.merge_episodes_to_arc(paths, series, provider)

            if not out_path or not os.path.exists(out_path):
                raise RuntimeError("Merge produced no output file.")

            print(f"  ✅ Merged script → {out_path}")

            with open(out_path, "r", encoding="utf-8") as f:
                merged = f.read()

            self._q.put({"type": "progress_base", "val": 1.0})
            self._q.put(
                {
                    "type": "done",
                    "script_path": out_path,
                    "script_content": merged,
                }
            )

        except Exception as e:
            import traceback

            if str(e) == "Cancelled by user":
                print("\n[INFO] Process cancelled by user.")
            else:
                print(f"[ERROR] {e}")
                traceback.print_exc(file=sys.stdout)
            self._q.put({"type": "error"})
        finally:
            sys.stdout = self._original_stdout

    def _start_mega_merge(self):
        if self._is_processing:
            return
        series = self._series_var.get()
        if not series or series.startswith("("):
            messagebox.showerror("No Series", "Select a series first.")
            return
        self._set_processing(True)
        self._reset_stats()
        self._clear_logs()
        sys.stdout = _Redirector(self._q)
        provider2 = self._model2_var.get()

        threading.Thread(
            target=self._run_mega_merge, args=(series, provider2), daemon=True
        ).start()

    def _run_mega_merge(self, series: str, provider: str):
        try:
            os.environ["OPENROUTER_MODEL_CALL_2"] = provider
            set_key(self._env_path, "OPENROUTER_MODEL_CALL_2", provider)

            episodes = self._get_episodes(series)
            paths = []
            
            for ep in episodes:
                sp = os.path.join(_PROJECTS_DIR, series, ep, "export", "script.txt")
                if os.path.exists(sp):
                    paths.append(sp)
                else:
                    print(f"[WARN] Missing script for {ep}, it will be excluded from the merge.")
            
            if not paths:
                raise ValueError("No episode scripts found. Run 'Generate Scripts (Call 2)' first.")

            chunk_size = 10
            chunks = [paths[i:i + chunk_size] for i in range(0, len(paths), chunk_size)]
            
            print(f"\n[MEGA MERGE] Total {len(paths)} episodes will be merged in {len(chunks)} chunks of {chunk_size}...")
            
            arc_script_paths = []
            
            for idx, chunk in enumerate(chunks):
                self._q.put({"type": "progress_base", "val": (idx / len(chunks)) * 0.8})
                if self._cancel.is_set(): raise Exception("Cancelled by user")
                
                arc_name = f"arc_{idx+1:02d}_script.txt"
                print(f"\n--- Processing Chunk {idx+1}/{len(chunks)} ({len(chunk)} episodes) ---")
                
                out_path = arc_merge.merge_episodes_to_arc(chunk, series, provider, output_filename=arc_name)
                if not out_path or not os.path.exists(out_path):
                    raise RuntimeError(f"Merge produced no output file for chunk {idx+1}.")
                
                arc_script_paths.append(out_path)
            
            self._q.put({"type": "progress_base", "val": 0.85})
            
            # Final Merge
            final_out_path = os.path.join(_PROJECTS_DIR, series, "script_merged", "merged_script.txt")
            
            if len(arc_script_paths) == 1:
                print("\n[MEGA MERGE] Only 1 chunk generated. Renaming to merged_script.txt...")
                import shutil
                shutil.copy2(arc_script_paths[0], final_out_path)
            else:
                if self._cancel.is_set(): raise Exception("Cancelled by user")
                print("\n--- Processing Final Mega Merge (combining all chunks) ---")
                
                final_out_dir = os.path.join(_PROJECTS_DIR, series, "script_merged")
                chapter_merge.merge_arcs_to_final(arc_script_paths, final_out_path, provider=provider)
                
            if not os.path.exists(final_out_path):
                raise RuntimeError("Final merge failed: merged_script.txt not found.")

            print(f"  ✅ Mega Merged script → {final_out_path}")

            with open(final_out_path, "r", encoding="utf-8") as f:
                merged = f.read()

            self._q.put({"type": "progress_base", "val": 1.0})
            self._q.put(
                {
                    "type": "done",
                    "script_path": final_out_path,
                    "script_content": merged,
                }
            )

        except Exception as e:
            import traceback

            if str(e) == "Cancelled by user":
                print("\n[INFO] Process cancelled by user.")
            else:
                print(f"[ERROR] {e}")
                traceback.print_exc(file=sys.stdout)
            self._q.put({"type": "error"})
        finally:
            sys.stdout = self._original_stdout

    # =========================================================================
    # Voiceover
    # =========================================================================
    def _start_voiceover(self):
        script_text = self._script_box.get("1.0", "end").strip()
        if not script_text:
            messagebox.showerror("No Script", "Load or generate a script first.")
            return
        series = self._series_var.get()
        if not series or series.startswith("("):
            messagebox.showerror("No Series", "Select a series first.")
            return
            
        merged_path = os.path.join(_PROJECTS_DIR, series, "script_merged", "merged_script.txt")
        if os.path.exists(merged_path):
            with open(merged_path, "r", encoding="utf-8") as f:
                script_text = f.read().strip()
            print("[INFO] Found merged script, using it for voiceover.")
        else:
            print("[INFO] No merged script found, using individual episode script.")

        self._set_processing(True)
        self._clear_logs()
        sys.stdout = _Redirector(self._q)

        threading.Thread(
            target=self._run_voiceover, args=(script_text, series), daemon=True
        ).start()

    def _run_voiceover(self, script_text: str, series: str):
        try:
            from core.audio_generator import AudioGenerator

            out_dir = os.path.join(_PROJECTS_DIR, series, "voiceover")
            os.makedirs(out_dir, exist_ok=True)

            print("[CHUNK] Generating voiceover…")
            print(
                f"  Voice: {self._vo_voice} | "
                f"Speed: {self._vo_rate} | Pitch: {self._vo_pitch}"
            )
            print(f"  Script: {len(script_text.split())} words")

            gen = AudioGenerator(
                voice=self._vo_voice, rate=self._vo_rate, pitch=self._vo_pitch
            )
            combined_path, _, _ = gen.generate_combined_audio(
                script_text, out_dir, callback=lambda m: print(m)
            )

            if combined_path:
                print(f"  ✅ Voiceover saved → {combined_path}")
            else:
                print(f"  ✅ Audio chunks saved → {out_dir}")
            self._q.put({"type": "done"})

        except Exception as e:
            import traceback

            if str(e) == "Cancelled by user":
                print("\n[INFO] Process cancelled by user.")
            else:
                print(f"[ERROR] Voiceover failed: {e}")
                traceback.print_exc(file=sys.stdout)
            self._q.put({"type": "error"})
        finally:
            sys.stdout = self._original_stdout

    # =========================================================================
    # Load Saved Script & Prompts dialog
    # =========================================================================
    def _open_prompt_editor(self):
        try:
            from ui.prompt_editor import PromptEditorWindow
            PromptEditorWindow(self)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open prompt editor: {e}")

    def _load_saved_script(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Project History (Full Series)")
        dialog.geometry("460x480")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="Choose a Series to load all episodes",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(pady=14)

        sf = ctk.CTkScrollableFrame(dialog)
        sf.pack(fill="both", expand=True, padx=14, pady=6)

        if not os.path.exists(_PROJECTS_DIR):
            os.makedirs(_PROJECTS_DIR, exist_ok=True)
            
        series_list = []
        for d in sorted(os.listdir(_PROJECTS_DIR)):
            sp = os.path.join(_PROJECTS_DIR, d)
            if not os.path.isdir(sp):
                continue
            eps = [
                e
                for e in os.listdir(sp)
                if e.startswith("ep_")
            ]
            if eps:
                series_list.append((d, len(eps)))

        if not series_list:
            ctk.CTkLabel(sf, text="No series found.").pack(pady=20)

        for series_name, ep_count in series_list:
            label = f"📁 {series_name} ({ep_count} episodes)"
            ctk.CTkButton(
                sf,
                text=label,
                anchor="w",
                command=lambda sn=series_name: self._load_full_series(sn, dialog),
            ).pack(fill="x", padx=4, pady=3)

    def _load_full_series(self, series_name: str, dialog):
        dialog.destroy()
        
        self._current_view_series = series_name
        self._current_view_ep = "FULL_SERIES"
        
        # Disable save button because it's a concatenated view
        if hasattr(self, '_save_intel_btn'):
            self._save_intel_btn.configure(state="disabled", fg_color="gray")
            
        self._intel_box.configure(state="normal")
        self._script_box.configure(state="normal")
        
        self._intel_box.delete("1.0", "end")
        self._script_box.delete("1.0", "end")
        
        eps = self._get_episodes(series_name)
        if not eps:
            self._intel_box.insert("end", f"No generated data found for {series_name}.")
            self._script_box.insert("end", f"No generated data found for {series_name}.")
            self._script_box.configure(state="disabled")
            return
            
        full_intel = []
        full_script = []
        
        for ep in eps:
            intel_path = os.path.join(_PROJECTS_DIR, series_name, ep, "export", "story_intel.json")
            script_path = os.path.join(_PROJECTS_DIR, series_name, ep, "export", "script.txt")
            
            if os.path.exists(intel_path):
                with open(intel_path, "r", encoding="utf-8") as f:
                    full_intel.append(f"=== EPISODE {ep} ===\n{f.read()}\n")
                    
            if os.path.exists(script_path):
                with open(script_path, "r", encoding="utf-8") as f:
                    full_script.append(f"=== EPISODE {ep} ===\n{f.read()}\n")
                    
        if full_intel:
            self._intel_box.insert("end", "\n".join(full_intel))
        else:
            self._intel_box.insert("end", f"No story intel found for {series_name}.")
            
        if full_script:
            self._script_box.insert("end", "\n".join(full_script))
        else:
            self._script_box.insert("end", f"No scripts found for {series_name}.")
            
        self._current_intel_original_text = self._intel_box.get("1.0", "end-1c")
        self._script_box.configure(state="disabled")

    # =========================================================================
    # API Key Manager
    # =========================================================================
    def _toggle_key(self, prov: str, entry: ctk.CTkEntry, btn: ctk.CTkButton):
        if btn.cget("text") == "Edit":
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.configure(show="*")
            btn.configure(
                text="Save",
                fg_color=["#3B8ED0", "#1F6AA5"],
                command=lambda: self._save_key(prov, entry),
            )
        else:
            self._save_key(prov, entry)

    def _save_key(self, prov: str, entry: ctk.CTkEntry):
        key = entry.get().strip()
        if not key:
            messagebox.showerror("Missing Key", "Enter an API key before saving.")
            return
        set_key(_ENV_PATH, f"{prov.upper()}_API_KEY", key)
        os.environ[f"{prov.upper()}_API_KEY"] = key
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.configure(show="")
        entry.insert(0, "••••••••••••••••")
        entry.configure(state="disabled")
        btn = self._api_btns[prov]
        btn.configure(
            text="Edit",
            fg_color="gray",
            command=lambda p=prov, e=entry, b=btn: self._toggle_key(p, e, b),
        )
        messagebox.showinfo("Saved", f"{prov.upper()} API Key saved permanently!")

    def _test_key(self, prov: str):
        entry = self._api_entries[prov]
        key = entry.get().strip()
        if key in ("", "••••••••••••••••"):
            key = os.getenv(f"{prov.upper()}_API_KEY", "")
        if not key:
            messagebox.showerror("Missing Key", f"No key found for {prov}.")
            return

        def _run():
            try:
                if prov == "gemini":
                    from google import genai

                    client = genai.Client(api_key=key)
                    client.models.generate_content(
                        model="gemini-2.5-flash", contents="hi"
                    )
                elif prov == "groq":
                    from openai import OpenAI

                    OpenAI(
                        base_url="https://api.groq.com/openai/v1", api_key=key
                    ).chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "user", "content": "hi"}],
                    )
                elif prov == "openai":
                    from openai import OpenAI

                    OpenAI(api_key=key).chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": "hi"}],
                    )
                elif prov == "anthropic":
                    import anthropic

                    anthropic.Anthropic(api_key=key).messages.create(
                        model="claude-3-5-sonnet-20241022",
                        max_tokens=10,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                elif prov == "openrouter":
                    from openai import OpenAI

                    OpenAI(
                        base_url="https://openrouter.ai/api/v1", api_key=key
                    ).chat.completions.create(
                        model="openrouter/auto",
                        messages=[{"role": "user", "content": "hi"}],
                    )
                self._q.put(
                    {
                        "type": "toast",
                        "title": "✅ Valid",
                        "msg": f"{prov.upper()} API key is working!",
                    }
                )
            except Exception as e:
                self._q.put(
                    {
                        "type": "toast",
                        "title": "❌ Failed",
                        "msg": f"{prov.upper()} test failed:\n{e}",
                    }
                )

        threading.Thread(target=_run, daemon=True).start()

    # =========================================================================
    # Voiceover Settings
    # =========================================================================
    def _open_vo_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Voiceover Settings")
        win.geometry("390x300")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        ctk.CTkLabel(
            win, text="TTS Engine Settings", font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=12)

        frm = ctk.CTkFrame(win, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=20)
        frm.grid_columnconfigure(1, weight=1)

        voice_var = ctk.StringVar(value=self._vo_voice)
        rate_var = ctk.StringVar(value=self._vo_rate)
        pitch_var = ctk.StringVar(value=self._vo_pitch)

        for r, (lbl, var, vals) in enumerate(
            [
                (
                    "Voice Actor:",
                    voice_var,
                    [
                        "en-US-ChristopherNeural",
                        "en-US-AriaNeural",
                        "en-US-GuyNeural",
                        "en-US-JennyNeural",
                    ],
                ),
                (
                    "Speed (Rate):",
                    rate_var,
                    ["-50%", "-25%", "-10%", "+0%", "+10%", "+25%", "+50%"],
                ),
                (
                    "Tone (Pitch):",
                    pitch_var,
                    ["-50Hz", "-25Hz", "-10Hz", "+0Hz", "+10Hz", "+25Hz", "+50Hz"],
                ),
            ]
        ):
            ctk.CTkLabel(frm, text=lbl).grid(row=r, column=0, sticky="w", pady=10)
            ctk.CTkOptionMenu(frm, variable=var, values=vals).grid(
                row=r, column=1, sticky="ew", padx=10, pady=10
            )

        def _save():
            self._vo_voice = voice_var.get()
            self._vo_rate = rate_var.get()
            self._vo_pitch = pitch_var.get()
            print(
                f"[Voiceover] Settings: {self._vo_voice}, "
                f"{self._vo_rate}, {self._vo_pitch}"
            )
            win.destroy()

        ctk.CTkButton(win, text="Save Settings", height=38, command=_save).pack(pady=16)

    # =========================================================================
    # Processing state helpers
    # =========================================================================
    def _set_processing(self, state: bool):
        self._is_processing = state
        self._cancel.clear()
        if state:
            self._start_time = time.time()
            for btn in [self._gen_btn, self._script_btn, self._merge_btn, self._mega_merge_btn, self._vo_btn]:
                btn.configure(state="disabled")
        else:
            self._gen_btn.configure(state="normal")
            self._vo_btn.configure(state="normal")
            self._update_pre_cost()

        self._cancel_btn.configure(state="normal" if state else "disabled")
        self._stat_phase.configure(
            text="Running…" if state else "Idle",
            text_color="#00ff00" if state else "white",
        )

    def _cancel_processing(self):
        self._cancel.set()
        self._cancel_btn.configure(state="disabled")
        self._stat_phase.configure(text="Cancelling…", text_color="orange")
        print(
            "[ERROR] Cancellation requested by user! "
            "Aborting after current API call…"
        )

    def _force_reset_ui(self):
        self._is_processing = False
        self._cancel.set()
        sys.stdout = self._original_stdout
        for btn in [self._gen_btn, self._merge_btn, self._mega_merge_btn, self._vo_btn]:
            btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._stat_phase.configure(text="UI Reset", text_color="orange")
        print("[WARN] Dashboard UI force reset. You can start a new task now.")

    def _reset_stats(self):
        self._total_panels = 0
        self._total_words = 0
        self._total_retries = 0
        self._total_cost = 0.0
        self._prog.set(0)
        for lbl, txt in [
            (self._stat_phase, "Starting…"),
            (self._stat_time, "00:00"),
            (self._stat_panels, "0"),
            (self._stat_retries, "0"),
            (self._stat_words, "0"),
            (self._stat_cost, "$0.000"),
        ]:
            lbl.configure(text=txt)
        self._ep_status_label.configure(text="")

    def _clear_logs(self):
        for box in [self._log_box, self._err_box]:
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.configure(state="disabled")

    # =========================================================================
    # Queue tick — called every 100 ms
    # =========================================================================
    def _tick(self):
        # Elapsed timer
        if self._is_processing and self._start_time:
            m, s = divmod(int(time.time() - self._start_time), 60)
            self._stat_time.configure(text=f"{m:02d}:{s:02d}")

        while not self._q.empty():
            try:
                item = self._q.get_nowait()
                t = item["type"]

                if t == "log":
                    msg = item["msg"]

                    if msg.startswith("[ERROR]"):
                        self._append(self._err_box, msg.replace("[ERROR]", "").strip())
                        continue

                    if msg.startswith("[STATS]"):
                        stat = msg.replace("[STATS]", "").strip()
                        if "=" in stat:
                            k, v = stat.split("=", 1)
                            if k == "total_panels":
                                self._stat_panels.configure(text=v)
                            elif k == "words":
                                self._stat_words.configure(text=v)
                            elif k == "cost":
                                self._stat_cost.configure(text=f"${float(v):.4f}")
                            elif k == "retries+=1":
                                self._total_retries += 1
                                self._stat_retries.configure(
                                    text=str(self._total_retries), text_color="orange"
                                )
                        continue

                    if msg.startswith("[PROGRESS_BASE]"):
                        v = float(msg.replace("[PROGRESS_BASE]", "").strip())
                        self._prog.set(v)
                        continue

                    if msg.startswith("[CHUNK]"):
                        chunk = msg.replace("[CHUNK]", "").strip()
                        self._stat_phase.configure(text=chunk)
                        self._append(self._log_box, f">> {chunk}")
                        cur = self._prog.get()
                        if cur < 0.95:
                            self._prog.set(cur + 0.03)
                        continue

                    self._append(self._log_box, msg)

                elif t == "ep_status":
                    self._ep_status_label.configure(text=item["msg"])

                elif t == "progress_base":
                    self._prog.set(item["val"])

                elif t == "toast":
                    title = item["title"]
                    if "fail" in title.lower() or "❌" in title:
                        messagebox.showerror(title, item["msg"])
                    else:
                        messagebox.showinfo(title, item["msg"])

                elif t == "done":
                    self._prog.set(1.0)
                    self._stat_phase.configure(text="✅ Finished", text_color="#00ff00")
                    self._is_processing = False
                    sys.stdout = self._original_stdout
                    for btn in [self._gen_btn, self._merge_btn, self._mega_merge_btn, self._vo_btn]:
                        btn.configure(state="normal")
                    self._cancel_btn.configure(state="disabled")

                    if item.get("intel_path") and os.path.exists(item["intel_path"]):
                        with open(item["intel_path"], "r", encoding="utf-8") as f:
                            self._set_box(self._intel_box, f.read())

                    if item.get("script_content"):
                        self._set_box(self._script_box, item["script_content"])
                    elif item.get("script_path") and os.path.exists(
                        item["script_path"]
                    ):
                        with open(item["script_path"], "r", encoding="utf-8") as f:
                            self._set_box(self._script_box, f.read())

                    # Refresh episode status checkboxes
                    self._on_series_change(self._series_var.get())

                elif t == "error":
                    self._stat_phase.configure(
                        text="❌ Error / Cancelled", text_color="#ff0000"
                    )
                    self._is_processing = False
                    sys.stdout = self._original_stdout
                    for btn in [self._gen_btn, self._merge_btn, self._mega_merge_btn, self._vo_btn]:
                        btn.configure(state="normal")
                    self._cancel_btn.configure(state="disabled")

            except queue.Empty:
                break

        self.after(100, self._tick)

    # =========================================================================
    # UI helpers
    # =========================================================================
    def _append(self, box: ctk.CTkTextbox, msg: str):
        box.configure(state="normal")
        box.insert("end", msg + "\n")
        box.see("end")
        box.configure(state="disabled")

    def _set_box(self, box: ctk.CTkTextbox, content: str):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", content)
        box.configure(state="disabled")
