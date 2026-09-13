from service import process_order
from database import save_record


def handle_request(order):
    return process_order(order)


def handle_request_direct(data):
    return save_record(data)
