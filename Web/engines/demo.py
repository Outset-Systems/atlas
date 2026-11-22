import os

from engines.static import StaticFileAdapter


class DemoFeedAdapter(StaticFileAdapter):

    name = "demo"

    def __init__(self, path, data_path):
        super().__init__(path)
        self.data_path = data_path

    def _fetch(self):
        if os.path.exists(self.data_path):
            return {}
        return super()._fetch()
