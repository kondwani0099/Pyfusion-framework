# PyFusion Framework

Description:
PyFusion is an open-source Python framework designed for the seamless development of both web and desktop applications. Combining the power of Python, Tkinter for desktop GUI, and web technologies for web interfaces, PyFusion aims to simplify the creation of cross-platform applications. In the future, it envisions becoming a comprehensive framework for developing various types of applications.

## Key Features

- **HTML Integration:** PyFusion seamlessly integrates HTML content within Python applications, offering a flexible approach to web development.
- **Tkinter GUI:** Leveraging Python's standard GUI library, PyFusion enables the creation of rich and responsive desktop applications.
- **Web Server:** The framework includes a built-in web server, allowing developers to host web applications directly from their Python environment.
- **Responsive Design:** PyFusion supports responsive design principles, ensuring a consistent user experience across different devices.
- **Cross-Platform Vision:** With a future goal of becoming a cross-platform framework, PyFusion aims to support the development of applications for multiple platforms.

## Screenshots 
![Alt Text](screenshots/app(3).png)


## Folder structure 

pyfusion/
|-- assets/
|   |-- images/
|       |-- home.png
|       |-- settings.png
|-- fusionlib/
|   |-- gui_framework.py
|   |-- ui_components.py
|   |-- web_server.py
|-- screens/
|   |-- settings_page.py
|-- web/
|   |-- index.html
|   |-- styles.css
|-- webapp.py
|-- desktop_app.py


```markdown


## Getting Started

Follow these steps to set up a virtual environment and install project dependencies.

### Prerequisites

- [Python](https://www.python.org/) (version 3.x recommended)

### Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/kondwani0099/pyfusion-framework.git
   ```

2. Navigate to the project directory:

   ```bash
   cd pyfusion-framework
   ```

3. Create a virtual environment:

   ```bash
   python -m venv venv
   ```

   If you're using Python 3.3 or newer, you can use the `python` command. If you're using Python 3.6 or newer, `venv` is included by default.

   ```bash
   python3 -m venv venv
   ```

4. Activate the virtual environment:

   - On Windows:

     ```bash
     source venv/Scripts/activate
     ```

   - On macOS and Linux:

     ```bash
     source venv/bin/activate
     ```

   After activation, your terminal prompt should change to indicate that you are now working within the virtual environment.

5. Install project dependencies:

   ```bash
   pip install -r requirements.txt
   ```
# If you are using docker 
To build and run your Docker image, use the following commands in the terminal:

   ```bash
   docker build -t your-image-name
   docker run -p 5000:5000 your-image-name
   ```
Replace your-image-name with a name for your Docker image.
Make sure Docker is installed on your system before running these commands.

### Usage

Developers can use PyFusion to build applications with a unified codebase for both desktop and web interfaces. The framework facilitates the creation of interactive forms, dynamic content, and seamless navigation between pages, laying the foundation for a versatile application development experience.

## Contribution

PyFusion is an open-source project, and contributions from the community are highly encouraged. Developers can contribute by reporting issues, suggesting improvements, or submitting pull requests. The project follows the MIT License, allowing for free use, modification, and distribution.


## License

This project is licensed under the [MIT License](LICENSE).





