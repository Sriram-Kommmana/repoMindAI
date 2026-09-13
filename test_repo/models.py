class User:
    def __init__(self, name):
        self.name = name

    def greet(self):
        return self._format_greeting()

    def _format_greeting(self):
        return f"Hello, {self.name}!"


class Order:
    def __init__(self, user, amount):
        self.user = user
        self.amount = amount

    def summary(self):
        return f"Order of {self.amount} for {self.user.name}"
