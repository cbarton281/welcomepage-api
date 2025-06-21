import logging

class LabelLoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger, label):
        super().__init__(logger, {'label': label})

    def process(self, msg, kwargs):
        # Only prepend the label (not the module), since the formatter already includes module
        return f"{self.extra['label']}: {msg}", kwargs

def new_logger(label, module_name=None):
    # If module_name is not given, use the caller's module
    if module_name is None:
        import inspect
        frame = inspect.currentframe()
        try:
            module_name = frame.f_back.f_globals['__name__']
        finally:
            del frame
    logger = logging.getLogger(module_name)
    return LabelLoggerAdapter(logger, label)
