import tkinter as tk
from tkhtmlview import HTMLLabel
import os
from PIL import Image, ImageTk
class AppBar(tk.Frame):
    def __init__(self, master=None, app_name=None, app_color=None, **kwargs):
        super().__init__(master, **kwargs)

        # Create a label with the specified app name and color
        self.label = tk.Label(self, text=app_name, font=('Helvetica', 16, 'bold'), foreground=app_color)
        self.label.pack(side=tk.LEFT, padx=10)



class BottomNavigation(tk.Frame):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, bg='white', **kwargs)

        # Create a canvas with a shadow
        self.canvas = tk.Canvas(self, bg='white', highlightthickness=0, width=600, height=60)
        self.canvas.pack(side=tk.TOP, fill=tk.X)

        # Draw a shadow on top of the canvas
        self.canvas.create_polygon(0, 0, 0, 10, 600, 10, 600, 0, fill='gray', outline='white')

        # Example icons (replace with your own)
        home_icon = self.load_icon("home.png")
        settings_icon = self.load_icon("settings.png")

        # Create buttons with icons
        home_button = tk.Button(self, image=home_icon, command=self.show_home)
        home_button.image = home_icon  # Keep a reference to prevent garbage collection
        home_button.pack(side=tk.LEFT, padx=20)

        settings_button = tk.Button(self, image=settings_icon, command=self.show_settings)
        settings_button.image = settings_icon
        settings_button.pack(side=tk.LEFT, padx=20)

    def load_icon(self, file_name, size=(30, 30)):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, "icons", file_name)

        # Load and resize the icon
        icon = Image.open(file_path)
        icon = icon.resize(size, Image.ANTIALIAS)
        return ImageTk.PhotoImage(icon)

    def load_iconnn(self, file_path, size=(30, 30)):

        # Load and resize the icon
        icon = Image.open(file_path)
        icon = icon.resize(size, Image.ANTIALIAS)
        return ImageTk.PhotoImage(icon)

    def show_home(self):
        # Add logic for showing the home screen
        print("Showing Home")

    def show_settings(self):
        # Add logic for showing the settings screen
        print("Showing Settings")

class BottomNavigationnn(tk.Frame):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.label = tk.Label(self, text="Bottom Navigation", font=('Helvetica', 12))
        self.label.pack(side=tk.LEFT, padx=10)
