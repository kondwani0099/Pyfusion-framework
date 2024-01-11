# app.py
import threading
from fusionlib.web_server import run_web_server

def change_page(app_window, page_name):
    html_file = f'web/{page_name}.html'
    css_file = f'web/{page_name}.css'

    with open(html_file, 'r') as f:
        html_content = f.read()

    with open(css_file, 'r') as f:
        css_styles = [{'name': 'style', 'properties': {'innerHTML': f.read()}}]

    app_window.html_label.set_html_content(html_content)
    app_window.html_label.set_css_styles(css_styles)

if __name__ == '__main__':
    # Run the web server in a separate thread
    web_server_thread = threading.Thread(target=run_web_server)
    web_server_thread.start()

 