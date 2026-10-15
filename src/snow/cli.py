"""The `snow` command: a dispatch table of lazily imported Phase 1 commands."""

import importlib
import inspect
import sys

# name -> "module:function". Modules that later plans add are imported only when run.
COMMANDS: dict[str, str] = {
    "run": "snow.hub.__main__:main",
    "setup": "snow.config.setup:main",
    "install-autostart": "snow.hub.autostart:install",
    "uninstall-autostart": "snow.hub.autostart:uninstall",
    "dev say": "snow.devtools:say",
    "dev kill": "snow.devtools:kill",
    "dev inject-wav": "snow.voice.devinput:main",
    "dev probe-models": "snow.brain.probe:main",
    "dev audition-voices": "snow.voice.audition:main",
    "dev record-negatives": "snow.voice.record_negatives:main",
}


def _help() -> str:
    width = max(map(len, COMMANDS))
    rows = [f"  {name.ljust(width)}  {target}" for name, target in COMMANDS.items()]
    return "usage: snow <command> [args]\n\ncommands:\n" + "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(_help())
        return 0
    name = next((n for n in (" ".join(args[:2]), args[0]) if n in COMMANDS), None)
    if name is None:
        print(f"snow: unknown command '{args[0]}'\n\n{_help()}", file=sys.stderr)
        return 2
    module_name, func_name = COMMANDS[name].split(":")
    try:
        func = getattr(importlib.import_module(module_name), func_name)
    except ModuleNotFoundError as e:
        # Only a not-yet-built command module; a broken import inside one is a real bug.
        if e.name and (module_name == e.name or module_name.startswith(e.name + ".")):
            print(f"snow: '{name}' is not available in this build", file=sys.stderr)
            return 2
        raise
    rest = args[len(name.split()) :]
    result = func(rest) if inspect.signature(func).parameters else func()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
