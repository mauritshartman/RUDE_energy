# SINGLETON.PY
#
# Definitions of a singleton metaclass, to be used for classes for which there should
# be only one instance (singleton pattern). Implemented for Python 3 according to:
# https://stackoverflow.com/questions/6760685/creating-a-singleton-in-python
#
# Author: MA Hartman
# Date: February 9, 2021
#


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]
