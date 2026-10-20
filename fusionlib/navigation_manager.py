class NavigationManager:
    """Manages application routes, navigation history, and page change listeners."""

    def __init__(self, initial_route="index"):
        self.navigation_state = {"route": initial_route, "params": None}
        self.history = [self.navigation_state.copy()]
        self.routes = {}
        self._listeners = []

    def register_route(self, route_name, html_path=None, css_path=None, handler=None):
        """Register a named route with optional template paths or callback handler."""
        self.routes[route_name] = {
            "html_path": html_path or f"web/{route_name}.html",
            "css_path": css_path or f"web/{route_name}.css",
            "handler": handler,
        }

    def on_navigate(self, callback):
        """Register a listener function(route, params) triggered on navigation."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def navigate(self, route, params=None):
        """Navigate to a specific route and notify all registered listeners."""
        self.navigation_state = {
            "route": route,
            "params": params or {},
        }
        self.history.append(self.navigation_state.copy())
        print(f"Navigating to '{route}' with params: {self.navigation_state['params']}")

        if route in self.routes and self.routes[route].get("handler"):
            self.routes[route]["handler"](self.navigation_state["params"])

        for listener in self._listeners:
            listener(route, self.navigation_state["params"])

    def back(self):
        """Navigate back to the previous route in history."""
        if len(self.history) > 1:
            self.history.pop()
            previous = self.history[-1]
            self.navigation_state = previous.copy()
            for listener in self._listeners:
                listener(previous["route"], previous["params"])
            return previous["route"]
        return self.get_current_route()

    def get_current_route(self):
        return self.navigation_state.get("route", None)

    def get_navigation_params(self):
        return self.navigation_state.get("params", None)
