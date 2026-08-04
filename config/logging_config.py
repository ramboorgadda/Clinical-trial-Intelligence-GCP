# central logging setup for the entire application
# without centralised logging, every developer will setup differently
# every log basically look uniform 
# timestamp | loglevel | file it came from | message
import logging # logging levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
import sys # we are going to write all the logs to stdout so cloud run captures automatically
# cloud run reads the stdout and sends it to google cloud logging

def setup_logging(name: str) -> logging.Logger:
    '''this function calls at the top of the every file
    each file will get its own logger, namespaced to that file path
    this means log lines will show, which file generated them'''
    
    logger = logging.getLogger(name) # either creates new or returns existing one
    if logger.handlers:
        return logger 
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout) # stream handlers sends log lines to the stream
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",datefmt="%Y-%m-%d %H:%M:%S"
    ))
    if not logger.hasHandlers():
        logger.addHandler(handler)
        logger.propagate = False # prevents log lines from being duplicated in the console
    return logger
