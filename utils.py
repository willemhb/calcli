import argumentparser as ap
from functools import wraps
from typing import Union


class CliApp(ap.ArgumentParser):
    """
    ArgumentParser subclass that implements some of the behavior of click.
    
    the flag, argument, and option wrappers are used to add command line arguments to the
    parser. They can be called as wrappers, but only return the decorated function.
    The __call__ method applies the final decorator that returns the wrapped function into a
    command line application.
    """
    def flag(self, *names, **kwargs):
        @wraps(fun)
        def wrapper(fun):
            self.add_argument(*names, action='store_true')
            return fun

        return wrapper

    def argument(self, name, **kwargs):
        @wraps(fun)
        def wrapper(fun):
            self.add_argument(name, **kwargs)
            return fun

        return wrapper

    def option(self, *names, **kwargs):
        @wraps(fun)
        def wrapper(fun):
            self.add_argument(*names, **kwargs)
            return fun

        return wrapper

    def __call__(self, fun):
        """
        Decorate the wrapped function.
        """
        @wraps(fun)
        def wrapper(fun):
            def inner(args: Union[list,tuple,None] = None):
                if args is None:
                    nmspc = self.parse_args()
                    nmspc["args"] = sys.argv[2:]

                else:
                    nmspc = self.parse_args()
                    nmspc["args"] = args

                
                status = fun(**vars(nmspc))
                exit(status)

            return inner

        return wrapper
