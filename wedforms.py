# app.py
import threading
import requests  # Import the requests library
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

    # Send a POST request to the server (example URL, update accordingly)
    post_data = {'username': 'example_user', 'password': 'example_password'}
    response = requests.post('http://localhost:5000/submit_form', data=post_data)

    # Print the server response (you can handle it according to your needs)
    print(response.text)

if __name__ == '__main__':
    # Run the web server in a separate thread
    web_server_thread = threading.Thread(target=run_web_server)
    web_server_thread.start()
