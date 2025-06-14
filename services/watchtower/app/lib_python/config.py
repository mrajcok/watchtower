import configparser, os, re, signal, threading
from   typing  import Callable, Optional
from   .shared import sigusr1_received

check_configs_func: Optional[Callable] = None
# Even though this is an asyncio-based service, using a blocking/threading lock
# is much easier than making most of the functions in this module async, which
# would then require all callers to also be async. Normally it is not a good
# idea to mix async and blocking code, but in this case it is acceptable
# because the lock will only be held for extremely short periods of time.
lock = threading.Lock()

def register_check_configs(check_func: Callable):
    'decorator to register a function to be called when the configs are reloaded'
    global check_configs_func
    check_configs_func = check_func

def read_configs():  # must only be called once before the runloop is started
    config_path          = f'conf/{main_section}.cfg'
    override_config_path = os.environ.get('OVERRIDE_CONFIG_PATH')
    if os.path.exists(config_path):
        config.read_file(open(config_path))
        if override_config_path and os.path.exists(override_config_path):
            with open(override_config_path) as f:
                override_configs = f.read()
                if re.search(r'\[\s*secure\s*\]', override_configs):
                    raise ValueError('secure configs cannot be overridden')
                config.read_string(override_configs)
    else:
        raise FileNotFoundError(f'config file {config_path} does not exist')
    if check_configs_func:  check_configs_func()

def apply_overrides():
    # read the main config file again to reset any override values that might
    # have been removed
    config_path          = f'conf/{main_section}.cfg'
    override_config_path = os.environ.get('OVERRIDE_CONFIG_PATH')
    with lock:
        config.remove_section(main_section)  # clear all but DEFAULTS
        config.read_file(open(config_path))
        if override_config_path and os.path.exists(override_config_path):
            with open(override_config_path) as f:
                override_configs = f.read()
                if 'secure_configs' in override_configs:
                    raise ValueError('secure_configs cannot be overridden')
                config.read_string(override_configs)
    if check_configs_func:  check_configs_func()

def read_defaults(defaults:str):  # must only be called before the runloop is started
    if '[DEFAULT]' not in defaults:
        defaults = f'[DEFAULT]\n{defaults}'
    config.read_string(defaults)

def get(key:str):
    with lock:
        return config.get(main_section, key)

def get_int(key:str):
    with lock:
        return config.getint(main_section, key)

def get_eval(key:str):
    'only numbers and math operators are allowed in the expression'
    with lock:
        value = config.get(main_section, key)
        if not re.match(r'^[0-9\+\-\*\/\(\)\s]+$', value):
            raise ValueError(f'invalid expression: {value}')
        return eval(value)

def getbool(key:str):
    with lock:
        return config.getboolean(main_section, key)

def secure_get(key:str):
    with lock:
        return config.get('secure', key, raw=True)

config       = configparser.ConfigParser(inline_comment_prefixes=('#',';'))
main_section = os.environ.get('SERVICE_NAME', 'watchtower')
# create main_section now so that class constructors can read default configs
# before the main section is read from the config file
config.read_string(f'[{main_section}]')
read_configs()

# Set up signal handler for SIGUSR1 to apply config overrides at runtime.
# Note that not all config values can be overridden at runtime however.
# When unit testing with the uvicorn --reload option, this signal handler will not get
# triggered. To test the signal handler, run the app without the --reload option
# or run the app with gunicorn, which does not support --reload with uvicorn workers.
# Gunicorn will restart all workers if a SIGHUP is received by the container, so that
# is way to apply all configs, but at the expense of restarting the workers. 
def handle_sigusr1(signum, frame):
    # the following line may not be safe to execute in a signal handler, so only
    # uncomment it when unit testing
    print(f'signal {signum} received, setting event', flush=True)
    sigusr1_received.set()  # background_coroutine() in lifecycle.py checks this flag

signal.signal(signal.SIGUSR1, handle_sigusr1)
