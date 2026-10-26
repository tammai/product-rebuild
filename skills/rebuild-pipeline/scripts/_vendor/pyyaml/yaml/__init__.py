# Load-only subset of PyYAML 6.0.3 (MIT, see ../LICENSE). Vendored so the plugin needs no pip
# install: the dumper, emitter, representer, serializer and libyaml bindings are left out, since
# nothing in this plugin writes YAML through a library. Import it through yamlio.py, never
# directly: yamlio is where PyYAML's YAML 1.1 habits (yes/no booleans, dates, sexagesimal
# integers, silent duplicate keys) are turned off.
from .error import *
from .tokens import *
from .events import *
from .nodes import *
from .loader import *

__version__ = '6.0.3'
