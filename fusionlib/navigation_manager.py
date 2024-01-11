class NavigationManager:
    def __init__(self):
        self.navigation_state = {}

    def navigate(self, route, params=None):
        self.navigation_state = {
            'route': route,
            'params': params
        }
        print(f'Navigating to {route} with params: {params}')

    def get_current_route(self):
        return self.navigation_state.get('route', None)

    def get_navigation_params(self):
        return self.navigation_state.get('params', None)
