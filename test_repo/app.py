from models import User, Order
from utils import add_and_double


def build_order(name, a, b):
    user = User(name)
    total = add_and_double(a, b)
    return Order(user, total)


def run():
    order = build_order("Alice", 2, 3)
    print(order.summary())
