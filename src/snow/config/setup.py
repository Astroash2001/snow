"""`snow setup`: the only way a key enters Snow (SAFE-09, D-24, D-25).

Input is hidden (getpass). A value is never echoed, printed, logged or measured.
"""

import argparse
import getpass

from snow.brain.config import ModelsConfig
from snow.config.secrets import (
    KNOWN_KEYS,
    KeySpec,
    delete_secret,
    get_secret,
    set_secret,
)
from snow.config.settings import load_config


def _all_keys() -> tuple[KeySpec, ...]:
    """The known keys plus any extra `key_name` a user added to models.toml."""
    known = {k.name for k in KNOWN_KEYS}
    try:
        providers = load_config("models.toml", ModelsConfig).providers.values()
    except (OSError, ValueError):
        return KNOWN_KEYS
    extra: list[KeySpec] = []
    for p in providers:
        if p.key_name not in known:
            known.add(p.key_name)
            extra.append(KeySpec(p.key_name, p.label, ""))
    return KNOWN_KEYS + tuple(extra)


def _prompt(spec: KeySpec) -> None:
    value = getpass.getpass(f"{spec.label} key (Enter to skip): ").strip()
    if not value:
        print(f"{spec.label}: skipped")  # D-25: stays not configured
        return
    if spec.prefix_hint and not value.startswith(spec.prefix_hint):
        # Names the expected prefix only, never what was typed.
        print(f"Warning: {spec.label} keys usually start with '{spec.prefix_hint}'.")
        if input("Store it anyway? [y/N] ").strip().lower() != "y":
            print(f"{spec.label}: not stored")
            return
    set_secret(spec.name, value)
    print(f"{spec.label}: stored")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="snow setup")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="show what is configured")
    group.add_argument("--only", metavar="NAME", help="prompt for one key")
    group.add_argument("--clear", metavar="NAME", help="delete one key")
    args = parser.parse_args(argv)

    keys = _all_keys()
    by_name = {k.name: k for k in keys}
    chosen = args.only or args.clear
    if chosen and chosen not in by_name:
        parser.error(f"unknown key '{chosen}'; choose from: {', '.join(by_name)}")

    if args.status:
        for k in keys:
            state = "configured" if get_secret(k.name) else "not configured"
            print(f"{k.label}: {state}")
    elif args.clear:
        delete_secret(args.clear)
        print(f"{by_name[args.clear].label}: cleared")
    elif args.only:
        _prompt(by_name[args.only])
    else:
        for k in keys:
            _prompt(k)
    return 0
