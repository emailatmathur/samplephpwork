import time
import datetime
import csv
import os
import tkinter as tk
from tkinter import ttk, messagebox

LOG_FILE = 'focus_log.csv'

class FocusSession:
    """
    Represents a single focus session.
    """
    def __init__(self, duration_minutes: int):
        if not isinstance(duration_minutes, int) or duration_minutes <= 0:
            raise ValueError("Duration must be a positive integer in minutes.")

        self.planned_duration_seconds = duration_minutes * 60
        self.actual_start_time_monotonic = None
        self.session_start_datetime = None

        self.is_active = False
        self.total_elapsed_time_before_current_run = 0
        self.session_never_started = True
        self.explicitly_stopped = False
        self.logged = False

    def __repr__(self):
        return (f"FocusSession(planned_duration={self.planned_duration_seconds // 60}min, "
                f"active={self.is_active}, actual_start_time_monotonic={self.actual_start_time_monotonic}, "
                f"accumulated_elapsed={self.total_elapsed_time_before_current_run}s, "
                f"stopped={self.explicitly_stopped}, logged={self.logged})")

    def start(self):
        if self.is_active:
            return False

        if self.explicitly_stopped: # If reset, it's like a new session
            # Re-initialize some critical state if we are "restarting" a reset session
            self.explicitly_stopped = False
            self.session_never_started = True
            self.total_elapsed_time_before_current_run = 0
            self.logged = False
            # session_start_datetime will be set below

        if self.get_remaining_time() <= 0 and not self.session_never_started:
            return False

        self.is_active = True
        self.actual_start_time_monotonic = time.monotonic()
        if self.session_never_started:
            self.session_start_datetime = datetime.datetime.now()

        self.session_never_started = False
        # self.explicitly_stopped = False # Moved to the top of start
        # self.logged = False # Moved to the top of start
        return True

    def pause(self):
        if not self.is_active:
            return False

        current_run_duration = time.monotonic() - self.actual_start_time_monotonic
        self.total_elapsed_time_before_current_run += current_run_duration
        self.is_active = False
        self.actual_start_time_monotonic = None

        if self.get_remaining_time() <= 0: # Log if pausing completes the session
            self._log_session_to_csv(status_override="Completed")
        return True

    def reset(self):
        # Log the session before resetting if it has run and not been logged
        # Check if it ran for a meaningful duration or was active
        if not self.logged and (self.get_current_elapsed_time() > 0 or self.is_active):
             self._log_session_to_csv(status_override="Reset")

        if self.is_active: # Ensure current run duration is captured if it was active
            current_run_duration = time.monotonic() - self.actual_start_time_monotonic
            self.total_elapsed_time_before_current_run += current_run_duration
            self.is_active = False

        # Reset core attributes for a fresh start
        self.actual_start_time_monotonic = None
        self.total_elapsed_time_before_current_run = 0
        self.session_never_started = True
        self.is_active = False
        self.logged = False
        self.explicitly_stopped = True # Mark as stopped/reset, start() will clear this if resumed
        # self.session_start_datetime = None # Clearing this makes it behave like a brand new session object
        return True


    def _log_session_to_csv(self, status_override=None):
        if self.logged:
            return
        if self.session_never_started and not self.is_active : # Don't log if nothing happened
             return

        # If it was active when log is called (e.g. reset while running), capture final bit of time
        current_focus_time = self.get_current_elapsed_time()

        file_exists = os.path.isfile(LOG_FILE)
        try:
            with open(LOG_FILE, 'a', newline='') as csvfile:
                fieldnames = ['session_start_datetime', 'planned_duration_minutes', 'actual_focused_seconds', 'status']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                if not file_exists or csvfile.tell() == 0:
                    writer.writeheader()

                session_status = status_override
                if not session_status:
                    if self.explicitly_stopped and current_focus_time < self.planned_duration_seconds:
                        session_status = "Reset" # or "Stopped Early"
                    # Check if remaining time is 0 or less, considering the already calculated current_focus_time
                    elif (self.planned_duration_seconds - current_focus_time) <= 0 :
                        session_status = "Completed"
                    else:
                        session_status = "Interrupted"


                data_to_log = {
                    'session_start_datetime': self.session_start_datetime.strftime("%Y-%m-%d %H:%M:%S") if self.session_start_datetime else "N/A",
                    'planned_duration_minutes': self.planned_duration_seconds // 60,
                    'actual_focused_seconds': int(round(current_focus_time)),
                    'status': session_status
                }
                writer.writerow(data_to_log)
                self.logged = True
        except IOError as e:
            if messagebox:
                messagebox.showerror("Log Error", f"Could not write to log file: {e}")
            else:
                print(f"Error logging session: {e}") # Fallback for non-GUI context


    def get_current_elapsed_time(self) -> float:
        if self.session_never_started and not self.is_active :
            return 0

        current_run_duration = 0
        if self.is_active and self.actual_start_time_monotonic:
            current_run_duration = time.monotonic() - self.actual_start_time_monotonic

        return self.total_elapsed_time_before_current_run + current_run_duration

    def get_remaining_time(self) -> float:
        elapsed = self.get_current_elapsed_time()
        remaining = self.planned_duration_seconds - elapsed
        return max(0, remaining)

    def _format_time(self, seconds: float) -> str:
        seconds = int(round(seconds))
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

class FocusMeterApp:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title("Focus Meter")

        self.default_session_minutes = 25 # Default, can be made configurable
        self.focus_session = FocusSession(self.default_session_minutes)
        self.focus_session.root = self.root # Give session a reference to root for after_cancel if needed (though better to handle in App)
        self.focus_session.timer_job_id = None # Store timer job ID on session, or app? App is better.

        self.timer_job_id = None # For Tkinter's after() method

        # --- Style Definitions ---
        self.APP_BG = "#F0F2F5"  # Light greyish blue
        self.TEXT_COLOR = "#343A40"  # Darker grey
        self.TIME_TEXT_COLOR = "#2C3E50"  # Even darker blue/grey for time
        self.STATUS_TEXT_COLOR = "#495057" # Medium dark grey for status

        self.BUTTON_START_BG = "#007BFF" # Blue
        self.BUTTON_START_FG = "#FFFFFF"
        self.BUTTON_START_ACTIVE_BG = "#0056b3" # Darker Blue

        self.BUTTON_PAUSE_BG = "#FFC107" # Amber
        self.BUTTON_PAUSE_FG = "#212529" # Dark text for Amber
        self.BUTTON_PAUSE_ACTIVE_BG = "#d39e00" # Darker Amber

        self.BUTTON_RESET_BG = "#6C757D" # Grey
        self.BUTTON_RESET_FG = "#FFFFFF"
        self.BUTTON_RESET_ACTIVE_BG = "#545b62" # Darker Grey

        self.RING_TRACK_COLOR = "#E9ECEF"
        self.RING_PROGRESS_COLOR = self.BUTTON_START_BG # Blue
        self.RING_PAUSED_COLOR = self.BUTTON_PAUSE_BG # Amber
        self.RING_COMPLETED_COLOR = "#28A745" # Green for success

        self.FONT_FAMILY_MAIN = "Segoe UI"
        self.FONT_TIME = (self.FONT_FAMILY_MAIN, 48, 'bold')
        self.FONT_STATUS = (self.FONT_FAMILY_MAIN, 11)
        self.FONT_BUTTON = (self.FONT_FAMILY_MAIN, 10, 'bold')
        self.FONT_LABEL = (self.FONT_FAMILY_MAIN, 10)

        self.root.configure(bg=self.APP_BG)
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam') # Or 'alt', 'default' - 'clam' tends to be more customizable
        except tk.TclError:
            pass # Keep default theme if clam is not available

        self.style.configure("TFrame", background=self.APP_BG)
        self.style.configure("TLabel", background=self.APP_BG, foreground=self.TEXT_COLOR, font=self.FONT_LABEL)

        self.style.configure("Time.TLabel", background=self.APP_BG, foreground=self.TIME_TEXT_COLOR, font=self.FONT_TIME)
        self.style.configure("Status.TLabel", background=self.APP_BG, foreground=self.STATUS_TEXT_COLOR, font=self.FONT_STATUS)

        # General TButton style (fallback, not very effective for BG/FG on all themes)
        self.style.configure("TButton", font=self.FONT_BUTTON, padding=(10, 6), borderwidth=0)

        # Specific button styles using a new name convention
        # Start Button Style
        self.style.configure("Start.TButton", foreground=self.BUTTON_START_FG, background=self.BUTTON_START_BG, font=self.FONT_BUTTON)
        self.style.map("Start.TButton",
                       background=[('active', self.BUTTON_START_ACTIVE_BG), ('disabled', self.APP_BG)],
                       foreground=[('disabled', self.TEXT_COLOR)])
        # Pause Button Style
        self.style.configure("Pause.TButton", foreground=self.BUTTON_PAUSE_FG, background=self.BUTTON_PAUSE_BG, font=self.FONT_BUTTON)
        self.style.map("Pause.TButton",
                       background=[('active', self.BUTTON_PAUSE_ACTIVE_BG), ('disabled', self.APP_BG)],
                       foreground=[('disabled', self.TEXT_COLOR)])
        # Reset Button Style
        self.style.configure("Reset.TButton", foreground=self.BUTTON_RESET_FG, background=self.BUTTON_RESET_BG, font=self.FONT_BUTTON)
        self.style.map("Reset.TButton",
                       background=[('active', self.BUTTON_RESET_ACTIVE_BG), ('disabled', self.APP_BG)],
                       foreground=[('disabled', self.TEXT_COLOR)])


        main_frame = ttk.Frame(self.root, padding="20 20 20 20", style="TFrame")
        main_frame.pack(expand=True, fill=tk.BOTH)

        self.time_label_var = tk.StringVar()
        time_label = ttk.Label(main_frame, textvariable=self.time_label_var, style="Time.TLabel")
        time_label.pack(pady=(10, 20)) # More space after time

        # Duration Entry Frame
        duration_frame = ttk.Frame(main_frame, style="TFrame")
        duration_frame.pack(pady=10)

        duration_text_label = ttk.Label(duration_frame, text="Duration (min):", style="TLabel")
        duration_text_label.pack(side=tk.LEFT, padx=(0,5))

        self.duration_var = tk.StringVar(value=str(self.default_session_minutes))
        # For ttk.Entry, styling background is tricky. It often follows system theme.
        # We ensure its frame background matches.
        self.duration_entry = ttk.Entry(duration_frame, textvariable=self.duration_var, width=5, font=(self.FONT_FAMILY_MAIN, 10))
        self.duration_entry.pack(side=tk.LEFT, padx=5)

        self.set_duration_button = ttk.Button(duration_frame, text="Set", command=self.apply_new_duration_from_button, style="Reset.TButton", width=5) # Using Reset style for Set
        self.set_duration_button.pack(side=tk.LEFT, padx=5)


        self.canvas_size = 300
        self.timer_canvas = tk.Canvas(main_frame, width=self.canvas_size, height=self.canvas_size, bg=self.APP_BG, highlightthickness=0)
        self.timer_canvas.pack(pady=20)

        # Define ring properties (colors already defined above)
        self.ring_margin = 15
        self.ring_width = 14 # Slightly thicker ring

        # Draw the background ring (static)
        self.timer_canvas.create_oval(
            self.ring_margin, self.ring_margin,
            self.canvas_size - self.ring_margin, self.canvas_size - self.ring_margin,
            outline=self.RING_TRACK_COLOR, width=self.ring_width, style=tk.ARC
        )
        # Foreground progress ring item (dynamic)
        self.ring_item = self.timer_canvas.create_oval(
            self.ring_margin, self.ring_margin,
            self.canvas_size - self.ring_margin, self.canvas_size - self.ring_margin,
            outline=self.RING_PROGRESS_COLOR, width=self.ring_width, style=tk.ARC
        )


        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=20, fill=tk.X, expand=False)
        button_frame.columnconfigure(0, weight=1) # Allow buttons to expand
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=1)

        # Apply specific styles to buttons
        self.start_button = ttk.Button(button_frame, text="Start", command=self.start_session, style="Start.TButton")
        self.start_button.grid(row=0, column=0, padx=10, pady=5, sticky=tk.EW)

        self.pause_button = ttk.Button(button_frame, text="Pause", command=self.pause_session, state=tk.DISABLED, style="Pause.TButton")
        self.pause_button.grid(row=0, column=1, padx=10, pady=5, sticky=tk.EW)

        self.reset_button = ttk.Button(button_frame, text="Reset", command=self.reset_session_ui_logic, state=tk.DISABLED, style="Reset.TButton")
        self.reset_button.grid(row=0, column=2, padx=10, pady=5, sticky=tk.EW)

        self.status_label_var = tk.StringVar()
        status_label = ttk.Label(main_frame, textvariable=self.status_label_var, style="Status.TLabel", wraplength=self.canvas_size, justify=tk.CENTER) # wraplength same as canvas
        status_label.pack(pady=(10,0)) # Reduced bottom padding

        self.reset_session_ui_logic() # Call reset to initialize display and session object correctly

    def update_time_display_text(self):
        # This now primarily updates based on the current focus_session state
        # It's called by run_timer_loop or after state changes like reset.
        remaining_seconds = self.focus_session.get_remaining_time()
        self.time_label_var.set(self.focus_session._format_time(remaining_seconds))

    def _apply_duration_from_entry(self, called_from_start=False):
        """Reads duration from entry, validates, and resets the session with new duration.
        Returns True if successful, False otherwise.
        If called_from_start is True, it won't show a "Duration set" message if timer starts immediately.
        """
        try:
            new_minutes = int(self.duration_var.get())
            if new_minutes <= 0:
                messagebox.showerror("Invalid Duration", "Duration must be a positive number of minutes.")
                return False

            # Only truly reset and change messages if the duration is different or it's an explicit "Set" button press
            if new_minutes != self.default_session_minutes or not called_from_start:
                 # Update the reference for next default
                self.default_session_minutes = new_minutes
                self.reset_session_ui_logic(duration_minutes=new_minutes) # Reset with new duration
                if not called_from_start: # Only show this if "Set" button was pressed
                    self.status_label_var.set(f"Duration set to {new_minutes} min. Press Start.")
            elif new_minutes == self.default_session_minutes and called_from_start:
                # If called from start and duration hasn't changed from the one already set in focus_session
                # no need to reset, just proceed.
                # However, focus_session might be a completed one, so a reset is generally needed if not active.
                if self.focus_session.get_remaining_time() <= 0 and not self.focus_session.session_never_started:
                    self.reset_session_ui_logic(duration_minutes=new_minutes)

            return True
        except ValueError:
            messagebox.showerror("Invalid Duration", "Please enter a valid number for minutes.")
            return False

    def apply_new_duration_from_button(self):
        """Called when the 'Set' button is pressed."""
        self._apply_duration_from_entry(called_from_start=False)


    def start_session(self):
        # If session is not active (i.e., not resuming a pause),
        # ensure the duration from the entry is applied.
        # This also handles the case where a session just completed and user presses start again.

        is_resuming = (not self.focus_session.is_active and
                       self.focus_session.get_current_elapsed_time() > 0 and
                       self.focus_session.get_remaining_time() > 0)

        if not is_resuming:
            # For a new session (not resuming), apply duration from entry.
            # This also handles starting after completion or after reset.
            if not self._apply_duration_from_entry(called_from_start=True):
                return # Don't start if duration is invalid or user cancels
        # If is_resuming, self.focus_session already exists and has its state, so we don't apply_duration.
        # We just call self.focus_session.start() below.

        if self.focus_session.start(): # start() handles resuming (if is_resuming was true) or starting new
            self.status_label_var.set("Focus session active...")
            self.start_button.config(state=tk.DISABLED, text="Start") # Ensure text is "Start" always when active
            self.pause_button.config(state=tk.NORMAL, text="Pause")
            self.reset_button.config(state=tk.NORMAL)
            self.duration_entry.config(state=tk.DISABLED) # Disable entry during active session
            self.run_timer_loop()
        else:
            # This might happen if focus_session.start() returned False for other reasons
            # (e.g. trying to start a completed session that wasn't properly reset by UI logic)
            self.status_label_var.set("Cannot start. Reset or check duration.")


    def pause_session(self):
        if self.focus_session.is_active: # Pausing
            if self.timer_job_id:
                self.root.after_cancel(self.timer_job_id)
                self.timer_job_id = None
            self.focus_session.pause() # This updates session's internal state
            elapsed_formatted = self.focus_session._format_time(self.focus_session.get_current_elapsed_time())
            self.status_label_var.set(f"Paused. {elapsed_formatted} elapsed.")
            self.start_button.config(state=tk.NORMAL, text="Resume")
            self.pause_button.config(state=tk.DISABLED)
            self.duration_entry.config(state=tk.DISABLED) # <<< REFINE: Keep duration entry disabled when paused
            self.draw_timer_ring() # Update ring immediately to paused state/color

    def reset_session_ui_logic(self, duration_minutes=None):
        """Handles GUI reset logic and re-initializes the FocusSession."""
        if self.timer_job_id:
            self.root.after_cancel(self.timer_job_id)
            self.timer_job_id = None

        # Use provided duration or current default_session_minutes
        current_duration_target = duration_minutes if duration_minutes is not None else self.default_session_minutes

        # Log previous session if it ran, before creating a new one
        if hasattr(self, 'focus_session') and self.focus_session: # Check if focus_session exists
            self.focus_session.reset() # This logs the session if it ran

        self.focus_session = FocusSession(current_duration_target)
        self.default_session_minutes = current_duration_target # Ensure default is updated
        self.duration_var.set(str(current_duration_target)) # Update entry field

        self.update_time_display_text()
        self.draw_timer_ring()

        self.status_label_var.set(f"Ready. Session: {current_duration_target} min. Press Start.")
        self.start_button.config(state=tk.NORMAL, text="Start")
        self.pause_button.config(state=tk.DISABLED)
        self.reset_button.config(state=tk.DISABLED) # Disabled until session starts
        self.duration_entry.config(state=tk.NORMAL) # Ensure entry is enabled


    def run_timer_loop(self):
        self.update_time_display_text()
        self.draw_timer_ring()

        if self.focus_session.is_active:
            remaining_time = self.focus_session.get_remaining_time()
            if remaining_time > 0:
                self.timer_job_id = self.root.after(1000, self.run_timer_loop) # Update every second
            else:
                self.focus_session.is_active = False # Ensure session is marked inactive
                self.focus_session._log_session_to_csv(status_override="Completed")
                self.status_label_var.set("Session completed! Well done.")
                messagebox.showinfo("Focus Meter", "Session Completed!")
                self.start_button.config(state=tk.NORMAL, text="Start") # Ready for new session after reset
                self.pause_button.config(state=tk.DISABLED)
                self.reset_button.config(state=tk.NORMAL)
                self.duration_entry.config(state=tk.NORMAL) # Re-enable entry after completion
                # Play sound (optional future feature)
        else: # Session is not active (paused or just completed/reset)
            self.draw_timer_ring() # Ensure ring is updated to final state


    def draw_timer_ring(self):
        """Updates the timer ring on the canvas."""
        # Clear previous arc segments if any (simpler to reconfigure existing item)
        # self.timer_canvas.delete("progress_arc")

        elapsed_time = self.focus_session.get_current_elapsed_time()
        total_duration = self.focus_session.planned_duration_seconds

        if total_duration == 0: # Avoid division by zero if session somehow has 0 duration
            angle = 0
        elif self.focus_session.explicitly_stopped or (not self.focus_session.is_active and elapsed_time == 0 and self.focus_session.session_never_started):
            # If reset or not started, show a full ring or empty based on preference
            # For now, let's show an empty (or default outline)
            angle = 0 # Should not happen with validation, but good default

        current_ring_color = self.progress_ring_color
        if self.focus_session.is_active:
            progress_percentage = (elapsed_time / total_duration)
            # To make it fill clockwise, extent should be negative. Start at top (90 deg).
            extent_angle = -progress_percentage * 359.9
        elif not self.focus_session.is_active and self.focus_session.get_current_elapsed_time() > 0 and self.focus_session.get_remaining_time() > 0 : # Paused
            progress_percentage = (elapsed_time / total_duration)
            extent_angle = -progress_percentage * 359.9
            current_ring_color = self.paused_ring_color
        elif not self.focus_session.is_active and self.focus_session.get_remaining_time() <= 0 and not self.focus_session.session_never_started : # Completed
            extent_angle = -359.9 # Full circle
            current_ring_color = self.RING_COMPLETED_COLOR # Use completed color
        else: # Not started, or reset
            extent_angle = 0 # Empty circle
            # For reset/not started, ensure a consistent initial color (e.g. progress color or track color)
            # If extent is 0, outline color might not matter much unless it's a very thick line.
            # Let's use progress_ring_color to indicate it's ready to start filling with that color.
            current_ring_color = self.RING_PROGRESS_COLOR

        self.timer_canvas.itemconfigure(self.ring_item,
                                        start=90,
                                        extent=extent_angle,
                                        outline=current_ring_color, # This sets the arc color
                                        style=tk.ARC)
        # Ensure the background oval always uses its track color (it's a separate item now)

if __name__ == '__main__':
    root = tk.Tk()
    app = FocusMeterApp(root)
    root.mainloop()
