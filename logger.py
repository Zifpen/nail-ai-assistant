import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s"
)

def get_logger(name):
    return logging.getLogger(name)
