"""Visible, ordinary desktop window for local browser focus experiments.

This utility has no hooks into the browser, keyboard, clipboard, or host OS.
The controller stays available when the overlay is hidden so it can be shown
again without any background or stealth behavior.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox, ttk


class BenignOverlay:
    """Manage one decorated Tkinter test window and its visible controls."""

    def __init__(self) -> None:
        self.controller = tk.Tk()
        self.controller.title("Proctoring Lab — Overlay Controls")
        self.controller.resizable(False, False)

        self.topmost = tk.BooleanVar(value=True)
        self.x = tk.StringVar(value="80")
        self.y = tk.StringVar(value="80")
        self.width = tk.StringVar(value="340")
        self.height = tk.StringVar(value="120")

        self.overlay = tk.Toplevel(self.controller)
        self.overlay.title("Proctoring Lab Test Overlay")
        self.overlay.geometry("340x120+80+80")
        self.overlay.minsize(220, 80)
        self.overlay.attributes("-topmost", True)
        self.overlay.protocol("WM_DELETE_WINDOW", self.hide)
        self.overlay.bind("<Configure>", self._update_geometry_fields)

        label = ttk.Label(
            self.overlay,
            text="PROCTORING LAB TEST OVERLAY",
            anchor="center",
            font=("TkDefaultFont", 11, "bold"),
            wraplength=300,
        )
        label.pack(fill="both", expand=True, padx=12, pady=12)

        frame = ttk.Frame(self.controller, padding=12)
        frame.grid(sticky="nsew")
        ttk.Label(
            frame,
            text="Visible local desktop test window. Click it to observe browser focus.",
            wraplength=360,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        ttk.Button(frame, text="Show", command=self.show).grid(row=1, column=0, padx=(0, 6))
        ttk.Button(frame, text="Hide", command=self.hide).grid(row=1, column=1, padx=(0, 6))
        ttk.Checkbutton(
            frame,
            text="Always on top",
            variable=self.topmost,
            command=self.toggle_topmost,
        ).grid(row=1, column=2, columnspan=2, sticky="w")

        for column, (caption, variable) in enumerate(
            (("X", self.x), ("Y", self.y), ("Width", self.width), ("Height", self.height))
        ):
            ttk.Label(frame, text=caption).grid(row=2, column=column, sticky="w", pady=(12, 2))
            ttk.Entry(frame, textvariable=variable, width=9).grid(
                row=3, column=column, sticky="w", padx=(0, 6)
            )

        ttk.Button(frame, text="Move / Resize", command=self.apply_geometry).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        ttk.Label(
            frame,
            text="You can also drag the overlay or resize it using its normal window border.",
            wraplength=360,
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _update_geometry_fields(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self.overlay:
            return
        self.x.set(str(self.overlay.winfo_x()))
        self.y.set(str(self.overlay.winfo_y()))
        self.width.set(str(self.overlay.winfo_width()))
        self.height.set(str(self.overlay.winfo_height()))

    def show(self) -> None:
        self.overlay.deiconify()
        self.overlay.lift()

    def hide(self) -> None:
        self.overlay.withdraw()

    def toggle_topmost(self) -> None:
        self.overlay.attributes("-topmost", self.topmost.get())

    def apply_geometry(self) -> None:
        try:
            x, y = int(self.x.get()), int(self.y.get())
            width, height = int(self.width.get()), int(self.height.get())
        except ValueError:
            messagebox.showerror("Invalid geometry", "Enter whole numbers for X, Y, width, and height.")
            return
        if width < 220 or height < 80 or width > 4000 or height > 4000:
            messagebox.showerror("Invalid size", "Width must be 220–4000 and height 80–4000.")
            return
        self.overlay.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def run(self) -> None:
        self.controller.mainloop()


def main() -> int:
    try:
        BenignOverlay().run()
    except tk.TclError as exc:
        print(f"Cannot open the overlay display: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
