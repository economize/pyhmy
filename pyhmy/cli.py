"""Wrapper for Harmony's CLI.

This module makes it easy for one to interact with the Harmony CLI (either
statically or dynamically linked). It also natively manages all of the keystore
related features to help with scripting.

Example:
    Below is a demo of how to import, manage keys, and interact with the CLI::
        >>> from pyhmy import cli
        >>> cli.single_call("hmy keys add test1")
        '**Important** write this seed phrase in a safe place, it is the only way to recover your account if you ever forget your password
        craft ... tobacco'
        >>> cli.get_accounts_keystore()
        {'test1': 'one1aqfeed538xf7n0cfh60tjaeat7yw333pmj6sfu'}
        >>> check_addr = cli.get_accounts_keystore()["test1"]
        >>> cli.get_accounts(check_addr)
        ['test1']
        >>> cli.single_call("hmy keys list", timeout=2)
        'NAME                    \t\t                ADDRESS\n\ntest1                                  \tone1aqfeed538xf7n0cfh60tjaeat7yw333pmj6sfu\n'
        >>> cli.get_accounts_keystore()
        {}

This module refers to `accounts` as the NAME/ALIAS of an `address` given to by the
CLI's account keystore.

Lastly, on init, this module tries to a find a file named `hmy` within the current
working directory. If found, said file will be the default binary used. Note that the
binary that is used by this module can be changed with the `set_binary` function.

Example:
    Below is a demo of how to set the CLI binary used by the module::
        >>> import os
        >>> env = cli.download("./bin/test", replace=False)
        >>> cli.environment.update(env)
        >>> new_path = os.getcwd() + "/bin/test"
        >>> new_path
        '/Users/danielvdm/go/src/github.com/harmony-one/pyhmy/bin/test'
        >>> from pyhmy import cli
        >>> cli.set_binary(new_path)
        True
        >>> cli.get_binary_path()
        '/Users/danielvdm/go/src/github.com/harmony-one/pyhmy/bin/test'

For more details, reference the documentation here: TODO gitbook docs
"""

import subprocess
import pexpect
import os
import shutil
import re
import stat
import sys
from pathlib import Path

import requests

from .util import get_bls_build_variables, get_gopath

if sys.platform.startswith("linux"):
    _libs = {"libbls384_256.so", "libcrypto.so.10", "libgmp.so.10", "libgmpxx.so.4", "libmcl.so"}
else:
    _libs = {"libbls384_256.dylib", "libcrypto.1.0.0.dylib", "libgmp.10.dylib", "libgmpxx.4.dylib", "libmcl.dylib"}
_accounts = {}  # Internal accounts keystore, make sure to sync when needed.
_account_keystore_path = "~/.hmy/account-keys"  # Internal path to account keystore, will match the current binary.
_binary_path = "hmy"  # Internal binary path.

environment = os.environ.copy()  # The environment for the CLI to execute in.


def _get_current_accounts_keystore():
    """
    Internal function that gets the current keystore from the CLI.

    :returns A dictionary where the keys are the account names/aliases and the
             values are their 'one1...' addresses.
    """
    curr_addresses = {}
    response = single_call("hmy keys list")
    lines = response.split("\n")
    if "NAME" not in lines[0] or "ADDRESS" not in lines[0]:
        raise ValueError("Name or Address not found on first line of key list")
    if lines[1] != "":
        raise ValueError("Unknown format: No blank line between label and data")
    for line in lines[2:]:
        columns = line.split("\t")
        if len(columns) != 2:
            break  # Done iterating through all of the addresses.
        name, address = columns
        curr_addresses[name.strip()] = address
    return curr_addresses


def _set_account_keystore_path():
    """
    Internal function to set the account keystore path according to the binary.
    """
    global _account_keystore_path
    response = single_call("hmy keys location").strip()
    if not os.path.exists(response):
        os.mkdir(response)
    _account_keystore_path = response


def _sync_accounts():
    """
    Internal function that UPDATES the accounts keystore with the CLI's keystore.
    """
    _set_account_keystore_path()
    _accounts.clear()
    _accounts.update(_get_current_accounts_keystore())


def get_accounts_keystore():
    """
    :returns A dictionary where the keys are the account names/aliases and the
             values are their 'one1...' addresses. The returned dictionary
             will be maintained as keys gets added and removed.
    """
    _sync_accounts()
    return _accounts


def is_valid_binary(path):
    """
    :param path: Path to the Harmony CLI binary (absolute or relative).
    :return: If the file at the path is a CLI binary.
    """
    path = os.path.realpath(path)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    try:
        proc = subprocess.Popen([path, "version"], env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        if not err:
            return False
        return "harmony" in err.decode().strip().lower()
    except (OSError, subprocess.CalledProcessError, subprocess.SubprocessError):
        return False


def set_binary(path):
    """
    :param path: The path of the CLI binary to use.
    :returns If the binary has been set.

    Note that the exposed keystore will be updated accordingly.
    """
    global _binary_path
    path = os.path.realpath(path)
    assert os.path.exists(path)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    if not is_valid_binary(path):
        return False
    _binary_path = path
    _sync_accounts()
    return True


def get_binary_path():
    """
    :return: The absolute path of the CLI binary.
    """
    return os.path.abspath(_binary_path)


def get_version():
    """
    :return: The version string of the CLI binary.
    """
    proc = subprocess.Popen([_binary_path, "version"], env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    if not err:
        raise RuntimeError(f"Could not get version.\n"
                           f"\tGot exit code {proc.returncode}. Expected non-empty error message.")
    return err.decode().strip()


def get_account_keystore_path():
    """
    :return: The absolute path to the account keystore of the CLI binary.
    """
    return os.path.abspath(_account_keystore_path)


def check_address(address):
    """
    :param address: A 'one1...' address.
    :return: Boolean of if the address is in the CLI's keystore.
    """
    return address in get_accounts_keystore().values()


def get_address(name):
    """
    :param name: The alias of a key used in the CLI's keystore.
    :return: The associated 'one1...' address.
    """
    return get_accounts_keystore().get(name, None)


def get_accounts(address):
    """
    :param address: The 'one1...' address
    :return: A list of account names associated with the param

    Note that a list of account names is needed because 1 address can
    have multiple names within the CLI's keystore.
    """
    return [acc for acc, addr in get_accounts_keystore().items() if address == addr]


def remove_account(name):
    """
    Note that this edits the keystore directly since there is currently no
    way to remove an address using the CLI.

    :param name: The alias of a key used in the CLI's keystore.
    :raises RuntimeError: If it failed to remove an account.
    """
    if not get_address(name):
        return
    keystore_path = f"{get_account_keystore_path()}/{name}"
    try:
        shutil.rmtree(keystore_path)
    except (shutil.Error, FileNotFoundError) as err:
        raise RuntimeError(f"Failed to delete dir: {keystore_path}\n"
                           f"\tException: {err}") from err
    _sync_accounts()


def remove_address(address):
    """
    :param address: The 'one1...' address to be removed.
    """
    for name in get_accounts(address):
        remove_account(name)
    _sync_accounts()


def single_call(command, timeout=60):
    """
    :param command: String of command to execute on CLI
    :param timeout: Optional timeout in seconds
    :returns: Decoded string of response from hmy CLI call
    :raises: RuntimeError if bad command
    """
    command_toks = command.split(" ")
    if re.match(".*hmy", command_toks[0]):
        command_toks = command_toks[1:]
    command_toks = [_binary_path] + command_toks
    try:
        response = subprocess.check_output(command_toks, env=environment, timeout=timeout).decode()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
        raise RuntimeError(f"Bad CLI args: `{command}`\n "
                           f"\tException: {err}") from err
    return response


def expect_call(command, timeout=60):
    """
    :param command: String fo command to execute on CLI
    :param timeout: Optional timeout in seconds
    :returns: A pexpect child program
    :raises: RuntimeError if bad command
    """
    command_toks = command.split(" ")
    if re.match(".*hmy", command_toks[0]):
        command_toks = command_toks[1:]
    try:
        proc = pexpect.spawn(f"{_binary_path}", command_toks, env=environment, timeout=timeout)
    except (pexpect.ExceptionPexpect, pexpect.TIMEOUT) as err:
        raise RuntimeError(f"Bad CLI args: `{command}`\n "
                           f"\tException: {err}") from err
    return proc


def download(path="./bin/hmy", replace=True, verbose=True):
    """
    Download the CLI binary to the specified path.
    Related files will be saved in the same directory.

    :param path: The desired path (absolute or relative) of the saved binary.
    :param replace: A flag to force a replacement of the binary/file.
    :param verbose: A flag to enable a report message once the binary is downloaded.
    :returns the environment to run the saved CLI binary.
    """
    path = os.path.realpath(path)
    parent_dir = Path(path).parent
    assert not os.path.isdir(path), f"path `{path}` must specify a file, not a directory."

    if not os.path.exists(path) or replace:
        old_cwd = os.getcwd()
        os.makedirs(parent_dir, exist_ok=True)
        os.chdir(parent_dir)
        hmy_script_path = os.path.join(parent_dir, "hmy.sh")
        with open(hmy_script_path, 'w') as f:
            f.write(requests.get("https://raw.githubusercontent.com/harmony-one/go-sdk/master/scripts/hmy.sh")
                    .content.decode())
        os.chmod(hmy_script_path, os.stat(hmy_script_path).st_mode | stat.S_IEXEC)
        same_name_file = False
        if os.path.exists(os.path.join(parent_dir, "hmy")) and Path(path).name != "hmy":  # Save same name file.
            same_name_file = True
            os.rename(os.path.join(parent_dir, "hmy"), os.path.join(parent_dir, ".hmy_tmp"))
        if verbose:
            subprocess.call([hmy_script_path, '-d'])
        else:
            subprocess.call([hmy_script_path, '-d'], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
        os.rename(os.path.join(parent_dir, "hmy"), path)
        if same_name_file:
            os.rename(os.path.join(parent_dir, ".hmy_tmp"), os.path.join(parent_dir, "hmy"))
        if verbose:
            print(f"Saved harmony binary to: `{path}`")
        os.chdir(old_cwd)

    env = os.environ.copy()
    files_in_parent_dir = set(os.listdir(parent_dir))
    if files_in_parent_dir.intersection(_libs) == _libs:
        if sys.platform.startswith("linux"):
            env["LD_LIBRARY_PATH"] = parent_dir
        else:
            env["DYLD_FALLBACK_LIBRARY_PATH"] = parent_dir
    elif os.path.exists(f"{get_gopath()}/src/github.com/harmony-one/bls") \
            and os.path.exists(f"{get_gopath()}/src/github.com/harmony-one/mcl"):
        env.update(get_bls_build_variables)
    else:
        raise RuntimeWarning(f"Could not get environment for downloaded hmy CLI at `{path}`")
    return env
