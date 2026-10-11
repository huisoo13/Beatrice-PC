"""Public news endpoints; credentials and HTTP handling belong to the client."""


class NewsApi:
    def __init__(self, client):
        self.client = client

    def events(self):
        return self.client.request('GET', '/news/events')
