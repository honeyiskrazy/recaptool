import customtkinter as ctk
from ui.processing_view import ProcessingView
from ui.review_view import ReviewView
from ui.script_dashboard import ScriptDashboard
import os

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Webtoon-to-CapCut Asset Generator")
        self.geometry("1100x750")
        
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self.current_view = None
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.show_processing_view()

    def show_processing_view(self):
        if self.current_view is not None:
            self.current_view.destroy()
        self.current_view = ProcessingView(self, self.show_review_view)
        self.current_view.grid(row=0, column=0, sticky="nsew")

    def show_review_view(self, project_session):
        if self.current_view is not None:
            self.current_view.destroy()
        self.current_view = ReviewView(self, project_session, self.show_processing_view)
        self.current_view.grid(row=0, column=0, sticky="nsew")
        
    def show_script_view(self):
        if self.current_view is not None:
            self.current_view.destroy()
        self.current_view = ScriptDashboard(self, on_back_callback=self.show_processing_view)
        self.current_view.grid(row=0, column=0, sticky="nsew")

    def on_closing(self):
        """Clean up background threads before exit."""
        try:
            # Signal any active processing to stop
            if self.current_view is not None:
                # ProcessingView has a cancel event
                if hasattr(self.current_view, '_cancel_event'):
                    self.current_view._cancel_event.set()
                # ScriptDashboard has a cancel event
                if hasattr(self.current_view, '_cancel'):
                    self.current_view._cancel.set()
        except Exception:
            pass
        self.destroy()
