import tkinter as tk
from tkhtmlview import HTMLLabel
from .ui_components import AppBar, BottomNavigation


class HTMLAppWindow:
    def __init__(self, app_name=None, app_color=None, html_content=None, css_styles=None):
        self.root = tk.Tk()
        self.root.title("HTML App Window")

        # Create an AppBar with the specified app name and color
        self.app_bar = AppBar(self.root, app_name=app_name, app_color=app_color)
        self.app_bar.pack(fill=tk.X)

        # Create an HTMLLabel widget to display HTML content
        self.html_label = HTMLLabel(self.root, html=html_content)
        self.html_label.pack(expand=tk.YES, fill=tk.BOTH)

        # Create BottomNavigation
        self.bottom_navigation = BottomNavigation(self.root)
        self.bottom_navigation.pack(fill=tk.X)

        # Apply CSS styles if provided
        if css_styles:
            # Apply CSS styles to the HTMLLabel widget
            self.apply_styles(css_styles)

        # Start the Tkinter event loop
        self.root.mainloop()

    def apply_styles(self, css_styles):
        # Apply CSS styles to the HTMLLabel widget (a basic implementation)
        # You may need a more sophisticated CSS parsing and application mechanism
        for style in css_styles:
            self.html_label.tag_configure(style['name'], **style['properties'])

